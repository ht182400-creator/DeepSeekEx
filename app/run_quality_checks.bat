@echo off
chcp 65001 >nul
REM DeepSeekEx 第三方质量检查统一入口
REM 依次执行: Ruff -> Bandit -> 编译 -> pytest -> coverage(90%%) -> 前端 ESLint -> JS 语法
REM 任何一步失败则设置 ERRORLEVEL=1 并停止后续步骤

setlocal
cd /d "%~dp0"

echo.
echo ========== [1/7] Ruff Python 静态分析 ==========
ruff check . --output-format=concise
if errorlevel 1 goto :failed

echo.
echo ========== [2/7] Bandit Python 安全扫描 ==========
bandit -q -r config.py main.py pow_solver.py providers.py -c bandit.yaml
if errorlevel 1 goto :failed

echo.
echo ========== [3/7] Python 编译检查 ==========
python -m py_compile config.py main.py pow_solver.py providers.py tests\test_main.py tests\test_providers.py tests\test_provider_helpers.py tests\test_web_session.py tests\test_pow_solver.py tests\test_web_provider.py tests\verify_e2e.py
if errorlevel 1 goto :failed

echo.
echo ========== [4/7] Pytest 全量测试 ==========
python -m coverage erase
python -m coverage run -m pytest -q
if errorlevel 1 goto :failed

echo.
echo ========== [5/7] 覆盖率报告(阈值 90%%) ==========
python -m coverage report -m
if errorlevel 1 goto :failed
python -m coverage xml -o tests\coverage.xml

echo.
echo ========== [6/7] 前端 ESLint 静态分析 ==========
cd /d "%~dp0frontend"
call node_modules\.bin\eslint.cmd data.js utils.js actions.js app.js
if errorlevel 1 goto :failed

echo.
echo ========== [7/7] 前端 JS 语法检查 ==========
for %%F in (data.js utils.js actions.js app.js) do (
    node --check %%F
    if errorlevel 1 goto :failed
)

echo.
echo ========== 全部检查通过 ==========
endlocal
exit /b 0

:failed
echo.
echo ========== 检查未通过，请修复后重试 ==========
endlocal
exit /b 1
