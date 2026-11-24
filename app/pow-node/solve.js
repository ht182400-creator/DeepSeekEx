/**
 * DeepSeek PoW WASM 求解 CLI
 * 从 stdin 读取 challenge JSON,求解后把 payload JSON 写到 stdout
 * Python 后端通过子进程调用,利用官方 WASM 的毫秒级性能
 */

const PowSolver = require('@rezaparsian/deepseek-pow-solver');

/**
 * 主流程:读取 stdin -> 求解 -> 输出 JSON
 */
async function main() {
  try {
    // 读取 stdin
    let input = '';
    for await (const chunk of process.stdin) {
      input += chunk;
    }
    // 剥离可能的 BOM(PowerShell 管道会加,Python subprocess 不会)
    input = input.replace(/^\uFEFF+/, '').trim();
    if (!input) {
      console.error('EMPTY_INPUT');
      process.exit(1);
    }

    const challenge = JSON.parse(input);

    // 初始化 WASM(每次进程启动一次,开销小)
    const solver = new PowSolver();
    await solver.init();

    const startTime = Date.now();
    const payload = solver.solve(challenge);
    const elapsed = Date.now() - startTime;

    // 输出 payload(附带耗时到 stderr,不污染 stdout 的 JSON)
    process.stderr.write(`SOLVE_MS=${elapsed}\n`);
    process.stdout.write(JSON.stringify(payload));
  } catch (exc) {
    process.stderr.write(`ERROR: ${exc.message}\n`);
    process.exit(1);
  }
}

main();
