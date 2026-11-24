@echo off
setlocal

REM ============================================================
REM DeepSeek Studio 一键启动脚本（文件编码：GBK/ANSI）
REM 功能：启动前 kill 掉占用端口的老进程，再启动 FastAPI 后端
REM 用法：双击运行；命令行加任意参数可跳过结尾的暂停
REM ============================================================

REM ---------- 配置区 ----------
set "PORT=20000"
set "APP_DIR=%~dp0app"
set "SKIP_PAUSE=%1"

echo ============================================
echo   DeepSeek Studio 启动脚本
echo ============================================
echo.

REM ---------- 检查 Python ----------
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 并加入 PATH。
    goto :fail
)

REM ---------- 检查 uvicorn ----------
python -c "import uvicorn, fastapi, httpx" >nul 2>&1
if errorlevel 1 (
    echo [错误] 缺少依赖，请先执行: pip install fastapi uvicorn httpx
    goto :fail
)

REM ---------- 清理端口上的老进程 ----------
echo [步骤 1/3] 清理端口 %PORT% 的老进程...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:":%PORT%" ^| findstr /C:"LISTENING" ^| findstr /V /C:"[::]"') do (
    echo   终止 PID %%P
    taskkill /F /PID %%P >nul 2>&1
)
ping -n 2 127.0.0.1 >nul 2>&1

REM ---------- 启动服务 ----------
echo.
echo [步骤 2/3] 启动 DeepSeek Studio...
start "DeepSeek-Studio-%PORT%" /D "%APP_DIR%" cmd /c "python -m uvicorn main:app --host 127.0.0.1 --port %PORT%"

REM ---------- 验证 ----------
echo.
echo [步骤 3/3] 验证服务...
ping -n 3 127.0.0.1 >nul 2>&1

netstat -ano | findstr /C:":%PORT%" | findstr /C:"LISTENING" >nul 2>&1
if errorlevel 1 goto :verify_fail

echo.
echo ============================================
echo   启动成功！
echo   访问地址：http://127.0.0.1:%PORT%
echo   首次使用请在页面右上角「设置」中配置后端
echo ============================================
goto :done

:verify_fail
echo.
echo [警告] 服务可能未正常启动，请查看新窗口中的错误信息。
goto :done

:fail
echo [错误] 启动失败。

:done
echo.
if "%SKIP_PAUSE%"=="" (
    echo 按任意键关闭本窗口（服务会在独立窗口继续运行）...
    pause >nul
)
exit /b 0
