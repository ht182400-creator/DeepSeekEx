// DeepSeek PoW 求解器(Go 纯算实现)
// 算法: DeepSeekHashV1 = Keccak-f[1600] 跳过 round 0
// 参数: rate=136, padding=0x06...0x80, output=32 bytes
// 性能: 约 13.4ms/difficulty=144000 (参考 ds2api 实测)
// 用法: 从 stdin 读取 challenge JSON,求解后把 payload JSON 写到 stdout

package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
)

// Keccak-f[1600] 轮常数
var roundConstants = [24]uint64{
	0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
	0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
	0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
	0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
	0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
	0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
	0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
	0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
}

// rho 旋转偏移 [x][y]
var rotationOffsets = [5][5]uint{
	{0, 36, 3, 41, 18},
	{1, 44, 10, 45, 2},
	{62, 6, 43, 15, 61},
	{28, 55, 25, 21, 56},
	{27, 20, 39, 8, 14},
}

func rotl64(v uint64, s uint) uint64 {
	if s == 0 {
		return v
	}
	return (v << s) | (v >> (64 - s))
}

// keccakF1600 执行 Keccak-f 排列,跳过 round 0(DeepSeekHashV1 变体)
func keccakF1600(state *[5][5]uint64) {
	for round := 1; round < 24; round++ {
		// Theta
		var c [5]uint64
		for x := 0; x < 5; x++ {
			c[x] = state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4]
		}
		var d [5]uint64
		for x := 0; x < 5; x++ {
			d[x] = c[(x+4)%5] ^ rotl64(c[(x+1)%5], 1)
		}
		for x := 0; x < 5; x++ {
			for y := 0; y < 5; y++ {
				state[x][y] ^= d[x]
			}
		}

		// Rho + Pi
		var b [5][5]uint64
		for x := 0; x < 5; x++ {
			for y := 0; y < 5; y++ {
				b[y][(2*x+3*y)%5] = rotl64(state[x][y], rotationOffsets[x][y])
			}
		}

		// Chi
		for x := 0; x < 5; x++ {
			for y := 0; y < 5; y++ {
				state[x][y] = b[x][y] ^ (^b[(x+1)%5][y] & b[(x+2)%5][y])
			}
		}

		// Iota
		state[0][0] ^= roundConstants[round]
	}
}

// deepseekHash 计算 DeepSeekHashV1 哈希,返回 64 位十六进制字符串
func deepseekHash(message string) string {
	data := []byte(message)
	const rate = 136
	padLen := rate - (len(data) % rate)
	var padded []byte
	if padLen == 1 {
		padded = append(append([]byte{}, data...), 0x86)
	} else {
		padded = append(append([]byte{}, data...), 0x06)
		padded = append(padded, make([]byte, padLen-2)...)
		padded = append(padded, 0x80)
	}

	var state [5][5]uint64
	for offset := 0; offset < len(padded); offset += rate {
		block := padded[offset : offset+rate]
		for i := 0; i < rate/8; i++ {
			lane := binary.LittleEndian.Uint64(block[i*8 : (i+1)*8])
			x, y := i%5, i/5
			state[x][y] ^= lane
		}
		keccakF1600(&state)
	}

	// 取前 32 字节
	var out [32]byte
	for i := 0; i < 4; i++ {
		x, y := i%5, i/5
		binary.LittleEndian.PutUint64(out[i*8:(i+1)*8], state[x][y])
	}
	return fmt.Sprintf("%x", out[:])
}

// challengeData 上游 challenge 结构
type challengeData struct {
	Algorithm  string `json:"algorithm"`
	Challenge  string `json:"challenge"`
	Salt       string `json:"salt"`
	Signature  string `json:"signature"`
	Difficulty int    `json:"difficulty"`
	ExpireAt   int64  `json:"expire_at"`
	TargetPath string `json:"target_path"`
}

// payload 求解结果(用于 x-ds-pow-response header)
type payload struct {
	Algorithm  string  `json:"algorithm"`
	Challenge  string  `json:"challenge"`
	Salt       string  `json:"salt"`
	Answer     float64 `json:"answer"`
	Signature  string  `json:"signature"`
	TargetPath string  `json:"target_path"`
}

// solvePow 求解 PoW challenge
func solvePow(ch *challengeData) *payload {
	prefix := ch.Salt + "_" + strconv.FormatInt(ch.ExpireAt, 10) + "_"
	target := strings.ToLower(ch.Challenge)

	limit := ch.Difficulty
	if limit > 500000 {
		limit = 500000 // 防止死循环
	}

	for nonce := 0; nonce < limit; nonce++ {
		candidate := prefix + strconv.Itoa(nonce)
		if deepseekHash(candidate) == target {
			return &payload{
				Algorithm:  ch.Algorithm,
				Challenge:  ch.Challenge,
				Salt:       ch.Salt,
				Answer:     float64(nonce),
				Signature:  ch.Signature,
				TargetPath: ch.TargetPath,
			}
		}
	}
	return nil
}

// selfTest 用官方 WASM 测试向量验证实现正确性
func selfTest() bool {
	vectors := [][2]string{
		{"", "e594808bc5b7151ac160c6d39a02e0a8e261ed588578403099e3561dc40c26b3"},
		{"testsalt_1700000000_42", "d4a2ea58c89e40887c933484868380c6f803eaa8dc53a3b9df8e431b921a4f09"},
		{"testsalt_1700000000_100000", "abea2f35796b65486e9be1b36f7878c66cab021e96faa473fdf4decd31f9ba30"},
		{"abc123salt_1700000000_12345", "74b3b7452745b70e85eb32ee7f0a9ec0381d42dd5137b695da915e104fc390e1"},
	}
	allOK := true
	for _, v := range vectors {
		actual := deepseekHash(v[0])
		ok := actual == v[1]
		fmt.Fprintf(os.Stderr, "TEST_VECTOR %s\n", map[bool]string{true: "PASS", false: "FAIL"}[ok])
		if !ok {
			fmt.Fprintf(os.Stderr, "  expected=%s actual=%s\n", v[1], actual)
		}
		allOK = allOK && ok
	}
	return allOK
}

// 主流程
func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "--selftest" {
		if selfTest() {
			fmt.Fprintln(os.Stderr, "SELFTEST_PASS")
			os.Exit(0)
		}
		fmt.Fprintln(os.Stderr, "SELFTEST_FAIL")
		os.Exit(1)
	}

	// 读取 stdin
	input, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: read stdin: %v\n", err)
		os.Exit(1)
	}
	// 兼容 BOM 与编码:
	// 1) UTF-16LE BOM (FF FE) -> 每两字节取低位转 UTF-8
	// 2) UTF-8 BOM (EF BB BF) -> 剥离
	if len(input) >= 2 && input[0] == 0xFF && input[1] == 0xFE {
		// PowerShell 管道默认 UTF-16LE
		runes := make([]rune, 0, len(input)/2)
		for i := 2; i+1 < len(input); i += 2 {
			code := uint16(input[i]) | uint16(input[i+1])<<8
			runes = append(runes, rune(code))
		}
		input = []byte(string(runes))
	} else {
		// UTF-8 BOM
		if len(input) >= 3 && input[0] == 0xEF && input[1] == 0xBB && input[2] == 0xBF {
			input = input[3:]
		}
	}
	inputStr := strings.TrimSpace(string(input))
	if inputStr == "" {
		fmt.Fprintln(os.Stderr, "ERROR: EMPTY_INPUT")
		os.Exit(1)
	}

	var ch challengeData
	if err := json.Unmarshal([]byte(inputStr), &ch); err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: parse challenge: %v\n", err)
		os.Exit(1)
	}

	if ch.Algorithm == "" {
		ch.Algorithm = "DeepSeekHashV1"
	}
	if ch.TargetPath == "" {
		ch.TargetPath = "/api/v0/chat/completion"
	}

	result := solvePow(&ch)
	if result == nil {
		fmt.Fprintln(os.Stderr, "ERROR: no solution found")
		os.Exit(1)
	}

	out, err := json.Marshal(result)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: marshal result: %v\n", err)
		os.Exit(1)
	}
	os.Stdout.Write(out)
}
