@echo off
REM 本文件为 GBK 编码（中文 Windows 默认代码页 936），请勿另存为 UTF-8，否则中文会乱码
setlocal EnableExtensions
REM 显式切到 936：与文件 GBK 编码一致，避免控制台代码页不符导致中文解析异常
chcp 936 >nul 2>nul
title 教材习题解析生成器 · 一键部署
color 0B

echo ============================================================
echo    教材习题解析生成器 · 一键部署（Windows）
echo ============================================================
echo    自动完成：环境检查 → 安装依赖 → 配置模型 → 初始化数据
echo    → 启动前后端 → 打开浏览器。重复运行不会重复安装。
echo ============================================================
echo    项目目录：%~dp0
echo.

REM pushd 而非 cd /d：兼容网络路径（UNC）与含空格/中文的目录
pushd "%~dp0"
set "ROOT=%CD%\"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV_PY=%BACKEND%\.venv\Scripts\python.exe"
set "PY_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "FE_INSTALL=pnpm install"
set "FE_DEV=pnpm dev --host 127.0.0.1"
REM 所有 Python 子进程输出固定 GBK，与中文控制台一致（避免中文乱码）
set "PYTHONIOENCODING=gbk"

REM ========== 0) 服务已在运行？直接打开浏览器 ==========
if /i "%~1"=="restart" goto :restart_services
set "BACK_UP=0"
set "FRONT_UP=0"
call :url_ok 8000 /api/health llm_mode
if not errorlevel 1 set "BACK_UP=1"
call :url_ok 5173 / exercise-solver-workbench
if not errorlevel 1 set "FRONT_UP=1"
if "%FRONT_UP%"=="0" (
    REM 兼容 Node 17+ 只监听 IPv6 回环（::1）的情况
    call :url_ok_local 5173 / exercise-solver-workbench
    if not errorlevel 1 set "FRONT_UP=1"
)
if "%BACK_UP%%FRONT_UP%"=="11" (
    echo [提示] 检测到后端 :8000 与前端 :5173 已在运行。
    call :stdin_is_console
    if "%IS_CONSOLE%"=="1" (
        echo        直接回车或 8 秒内无操作 = 打开浏览器；输入 R 回车 = 重启服务后再打开。
        call :ask_restart
        if "%RESTART%"=="1" goto :restart_services
    ) else (
        echo        非交互环境：直接打开浏览器（如需重启请运行：一键部署.bat restart）
    )
    start "" http://localhost:5173
    call :sleep 3
    popd
    exit /b 0
)

REM ========== 0.5) 端口被其他程序占用？先拦下，避免带病启动 ==========
if "%BACK_UP%"=="0" (
    call :port_busy 8000
    if not errorlevel 1 (
        echo [警告] 端口 8000 已被其他程序占用（响应的不是本项目后端）。
        call :offer_kill 8000
        if errorlevel 1 (
            echo        已取消：请手动结束占用进程后重试（常见残留：上次未关掉的 python.exe）。
            pause
            popd
            exit /b 1
        )
    )
)
if "%FRONT_UP%"=="0" (
    call :port_busy 5173
    if not errorlevel 1 (
        echo [警告] 端口 5173 已被其他程序占用。
        call :offer_kill 5173
        if errorlevel 1 (
            echo        已取消：请手动结束占用进程后重试（常见残留：node.exe）。
            pause
            popd
            exit /b 1
        )
    )
)

REM ========== 0.6) 磁盘空间（软提醒，不阻断） ==========
set "FREEGB=-1"
for /f %%a in ('powershell -NoProfile -Command "try{[math]::Floor((Get-PSDrive (Get-Item '%ROOT%').PSDrive.Name).Free/1GB)}catch{-1}"') do set "FREEGB=%%a"
if not "%FREEGB%"=="-1" if %FREEGB% LSS 5 (
    echo [警告] 磁盘剩余空间约 %FREEGB% GB：依赖与模型总计约需 3 GB，空间不足会导致安装失败。
    echo.
)

REM ========== 1) 后端运行环境（Python 3.11+） ==========
set "VENV_OK=0"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>nul
    if not errorlevel 1 set "VENV_OK=1"
)
if not "%VENV_OK%"=="1" goto :no_venv
"%VENV_PY%" -c "import sys;print(sys.version.split()[0])" >"%TEMP%\_oc_venvver.txt" 2>nul
set "VENVVER="
set /p VENVVER=<"%TEMP%\_oc_venvver.txt"
echo [1/6] 后端运行环境就绪：已有虚拟环境（Python %VENVVER%）
goto :env_ready

:no_venv
if exist "%BACKEND%\.venv" (
    echo       已有虚拟环境不可用（可能来自其他系统或已损坏），正在清理重建...
    rmdir /s /q "%BACKEND%\.venv"
)
set "BASEPY="
call :try_python python
if not defined BASEPY call :try_python py -3.13
if not defined BASEPY call :try_python py -3.12
if not defined BASEPY call :try_python py -3.11
if not defined BASEPY call :try_python py
if not defined BASEPY (
    echo [错误] 未检测到 Python 3.11 或更高版本（已尝试 python / py -3.13 / py -3.12 / py -3.11）。
    echo        请从官网安装最新版：https://www.python.org/downloads/
    echo        安装时务必勾选 "Add python.exe to PATH"；装好后重新双击本文件。
    echo.
    pause
    popd
    exit /b 1
)
echo [1/6] Python 就绪：%PYVERCAND%（命令：%BASEPY%）
echo [2/6] 创建后端虚拟环境（backend\.venv）...
%BASEPY% -m venv "%BACKEND%\.venv"
if errorlevel 1 (
    echo [错误] 虚拟环境创建失败：请确认磁盘空间充足、具备目录写入权限。
    goto :fail
)

:env_ready
"%VENV_PY%" -c "import fastapi, chromadb, fastembed" >nul 2>nul
if errorlevel 1 (
    echo       正在安装后端依赖（首次约 3~8 分钟，请耐心等待）...
    "%VENV_PY%" -m pip install --upgrade pip -i %PY_MIRROR% >nul 2>nul
    "%VENV_PY%" -m pip install -e "%BACKEND%" -i %PY_MIRROR%
    if errorlevel 1 (
        echo       镜像源安装失败，改用官方 PyPI 重试...
        "%VENV_PY%" -m pip install -e "%BACKEND%"
        if errorlevel 1 (
            echo [错误] 依赖安装失败：请检查网络连接（公司网络可能需要代理），或稍后重试。
            goto :fail
        )
    )
)
echo [2/6] 后端依赖就绪

REM ========== 3) 前端依赖 ==========
where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Node.js（需要 20 或更高版本）。
    echo        请从官网安装：https://nodejs.org/zh-cn  （安装后重开本窗口再试）
    echo.
    pause
    popd
    exit /b 1
)
set "NODEMAJOR="
for /f "tokens=1 delims=." %%a in ('node --version 2^>nul') do set "NODEMAJOR=%%a"
set "NODEMAJOR=%NODEMAJOR:v=%"
if defined NODEMAJOR if %NODEMAJOR% LSS 20 (
    echo [错误] Node.js 版本过低：当前 %NODEMAJOR%.x（需要 20 或更高）。
    echo        请升级 Node.js：https://nodejs.org/zh-cn
    pause
    popd
    exit /b 1
)
where pnpm >nul 2>nul
if errorlevel 1 (
    echo       未检测到 pnpm，尝试安装（npm 或 corepack 两种方式）...
    call npm install -g pnpm >nul 2>nul
    where pnpm >nul 2>nul
    if errorlevel 1 (
        call corepack prepare pnpm@latest --activate >nul 2>nul
        where pnpm >nul 2>nul
    )
    if errorlevel 1 (
        echo       pnpm 安装未成功，改用 npm 安装前端依赖（功能一致，仅包管理器不同）。
        set "FE_INSTALL=npm install"
        set "FE_DEV=npm run dev -- --host 127.0.0.1"
    )
)
if not exist "%FRONTEND%\node_modules\.bin\vite.cmd" if not exist "%FRONTEND%\node_modules\.bin\vite" (
    echo [3/6] 安装前端依赖（首次约 1~3 分钟）...
    pushd "%FRONTEND%"
    %FE_INSTALL%
    if errorlevel 1 (
        popd
        echo [错误] 前端依赖安装失败：请检查网络（npm 源可尝试：npm config set registry https://registry.npmmirror.com）。
        goto :fail
    )
    popd
)
echo [3/6] 前端依赖就绪

REM ========== 4) 配置大模型 API（交互式三选一） ==========
call :ollama_check
if "%OLLAMA_STATE%"=="running" echo [4/6] 本地 Ollama：已安装且正在运行
if "%OLLAMA_STATE%"=="installed" echo [4/6] 本地 Ollama：已安装（服务未启动）
if "%OLLAMA_STATE%"=="missing" echo [4/6] 本地 Ollama：未安装（选择本地模型前需先安装）

if exist "%BACKEND%\.env" (
    echo       已存在 backend\.env（沿用现有配置）
    call :ensure_ollama_model
    call :env_report
    goto :after_env
)

copy /y "%ROOT%.env.example" "%BACKEND%\.env" >nul
echo ------------------------------------------------------------
echo  首次部署：请选择解析生成使用的大模型方式
echo    1 - 云端 API（需自备 Key：DeepSeek / 智谱 等 OpenAI 兼容端点）
echo    2 - 本地 Ollama（免费离线；自动选用本机已有模型，没有则拉取最小模型）
echo    3 - 离线演示模式（不调用任何大模型，仅演示流程与评测）
echo ------------------------------------------------------------
set /p CHOICE=请输入 1 / 2 / 3 后回车：
if "%CHOICE%"=="2" goto :cfg_ollama
if "%CHOICE%"=="3" goto :cfg_mock
goto :cfg_cloud

:cfg_cloud
echo.
echo 即将打开记事本，请填写 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 后保存关闭。
echo （保存时若提示编码，选择 UTF-8 或不更改编码均可）
pause
notepad "%BACKEND%\.env"
call :env_report
goto :after_env

:cfg_mock
call :set_env_kv LLM_MOCK true
echo 已设为离线演示模式（LLM_MOCK=true）：解析由检索片段拼装，不调用大模型。
call :env_report
echo 之后可随时在网页「模型设置」面板切换为云端或本地模型。
goto :after_env

:cfg_ollama
call :set_env_kv LLM_PROVIDER ollama
if "%OLLAMA_STATE%"=="missing" (
    echo.
    echo 本机尚未安装 Ollama，即将打开官方下载页（约 700MB，安装后无需重启电脑）。
    echo 安装完成后：启动 Ollama（开始菜单）→ 回到本窗口按任意键继续。
    start "" https://ollama.com/download
    pause
)
if "%OLLAMA_STATE%"=="installed" (
    echo Ollama 已安装但服务未启动：请先从开始菜单打开 Ollama，然后按任意键继续。
    pause
)
call :url_ok 11434 /api/version version
if errorlevel 1 (
    echo [提示] Ollama 服务当前不可达：可稍后在网页「模型设置」面板里一键拉取模型。
    call :env_report
    goto :after_env
)
REM ---- 本机有哪个模型就用哪个；一个都没有才拉最小体积的 ----
call :pick_ollama_model
if not defined PICKED_MODEL goto :cfg_ollama_pull
call :set_env_kv OLLAMA_MODEL %PICKED_MODEL%
echo 已检测到本机可用模型：%PICKED_MODEL%（直接使用，无需下载）
call :env_report
goto :after_env

:cfg_ollama_pull
echo 本机尚未安装任何 Ollama 模型，将拉取体积最小的 qwen2.5:0.5b（约 400MB，占用内存最小，
echo 生成质量有限；如需更好效果，可稍后在网页「模型设置」面板拉取更大的模型，如 qwen2.5:3b）。
ollama pull qwen2.5:0.5b
if errorlevel 1 (
    echo [提示] 模型拉取未完成：可稍后在网页「模型设置」面板里重试。
) else (
    call :set_env_kv OLLAMA_MODEL qwen2.5:0.5b
    echo 模型就绪：qwen2.5:0.5b 已写入 backend\.env
)
call :env_report
goto :after_env

:after_env

REM ========== 5) 初始化数据库与样例语料 ==========
echo [5/6] 初始化数据库并导入样例语料（幂等；首次约 1~2 分钟）...
if not exist "%BACKEND%\models_cache" (
    echo [警告] 未找到 backend\models_cache（本地嵌入模型，约 95MB）：
    echo        首次检索时将尝试联网下载；若网络受限，请从完整交付包中恢复该目录。
)
pushd "%BACKEND%"
".venv\Scripts\python.exe" "..\scripts\init_db.py" --seed-samples
if errorlevel 1 (
    echo [警告] 初始化未完全成功：可稍后在网页「资料上传」面板手动导入样例语料。
)
popd

REM ========== 6) 启动前后端并打开浏览器 ==========
:start_services
echo [6/6] 启动服务（会弹出两个命令行窗口，关闭它们即停止服务）...
if "%BACK_UP%"=="0" start "教材解析-后端 :8000" /d "%BACKEND%" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
if "%FRONT_UP%"=="0" start "教材解析-前端 :5173" /d "%FRONTEND%" cmd /k "%FE_DEV%"

echo 等待服务就绪（首次启动/首次加载模型可能需要一两分钟）...
set /a TRIES=0
:waitloop
call :sleep 2
call :url_ok 8000 /api/health llm_mode
if errorlevel 1 goto :wait_more
call :url_ok 5173 / exercise-solver-workbench
if not errorlevel 1 goto :ready
:wait_more
set /a TRIES+=1
set /a HALF=TRIES %% 15
if %HALF%==0 echo    ...仍在启动中（已等待约 %TRIES% 秒），请留意弹出的两个窗口
if %TRIES% GEQ 60 goto :timeout
goto :waitloop

:ready
echo.
echo ============================================================
echo    部署完成！
echo      工作台地址：  http://127.0.0.1:5173
echo      接口文档：    http://127.0.0.1:8000/docs
echo    停止服务：关闭弹出的「教材解析-后端 / 前端」两个窗口
echo    再次启动：重新双击本文件（服务已运行时可选重启）
echo ============================================================
for /f "delims=" %%m in ('powershell -NoProfile -Command "try{(Invoke-RestMethod -TimeoutSec 3 'http://127.0.0.1:8000/api/health').llm_mode}catch{''}"') do set "LIVE_MODE=%%m"
for /f "delims=" %%m in ('powershell -NoProfile -Command "try{(Invoke-RestMethod -TimeoutSec 3 'http://127.0.0.1:8000/api/health').llm_model}catch{''}"') do set "LIVE_MODEL=%%m"
if /i "%LIVE_MODE%"=="ollama" echo    当前生成模式：本地 Ollama（免费离线）%LIVE_MODEL%
if /i "%LIVE_MODE%"=="cloud"  echo    当前生成模式：云端 API（按量计费）%LIVE_MODEL%
if /i "%LIVE_MODE%"=="mock"   echo    当前生成模式：离线模板（不调用大模型）
echo    切换模式/调参数：工作台左侧「模型设置」面板（保存即生效）
start "" http://localhost:5173
call :sleep 6
popd
exit /b 0

:timeout
echo.
echo [警告] 等待服务启动超时（已等待约 3 分钟）。请检查弹出的两个窗口中的报错：
echo        后端窗口：多为 .env 配置有误（键名拼写 / 端口冲突）
echo        前端窗口：多为依赖未装全（删除 frontend\node_modules 后重新双击本文件）
echo.
pause
popd
exit /b 1

:fail
echo.
echo [错误] 部署过程中出现问题，请把上方报错信息截图给维护者。
echo.
pause
popd
exit /b 1

REM ---- 工具：探测标准输入是否为真实控制台（1=是，0=否）
:stdin_is_console
set "IS_CONSOLE=0"
for /f "delims=" %%c in ('powershell -NoProfile -Command "[Console]::IsInputRedirected" 2^>nul') do if /i "%%c"=="False" set "IS_CONSOLE=1"
exit /b 0

REM ---- 工具：询问是否重启服务（choice 8 秒超时默认打开浏览器；非控制台环境自动走默认）
:ask_restart
set "RESTART=0"
choice /c OR /t 8 /d O /n >nul 2>nul
if errorlevel 2 set "RESTART=1"
exit /b 0

REM ---- 工具：挑选本机已安装的 Ollama 模型（优先 qwen 系列，其次第一个；无模型则不设 PICKED_MODEL）
:pick_ollama_model
set "PICKED_MODEL="
set "FIRST_MODEL="
for /f "skip=1 tokens=1" %%m in ('ollama list 2^>nul') do (
    if not defined FIRST_MODEL set "FIRST_MODEL=%%m"
)
for /f "tokens=1" %%m in ('ollama list 2^>nul ^| findstr /i /c:"qwen"') do (
    if not defined PICKED_MODEL set "PICKED_MODEL=%%m"
)
if not defined PICKED_MODEL if defined FIRST_MODEL set "PICKED_MODEL=%FIRST_MODEL%"
exit /b 0

REM ---- 工具：.env 用 ollama 但所选模型本机未安装时，自动换成本机已有模型
:ensure_ollama_model
if not "%OLLAMA_STATE%"=="running" exit /b 0
set "ENV_OLLAMA_MODEL="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"OLLAMA_MODEL=" "%BACKEND%\.env" 2^>nul') do set "ENV_OLLAMA_MODEL=%%v"
if not defined ENV_OLLAMA_MODEL exit /b 0
ollama list 2>nul | findstr /i /c:"%ENV_OLLAMA_MODEL%" >nul
if not errorlevel 1 exit /b 0
call :pick_ollama_model
if not defined PICKED_MODEL (
    echo [提示] .env 中的 Ollama 模型「%ENV_OLLAMA_MODEL%」本机未安装，且当前没有任何已安装模型（可在网页「模型设置」面板拉取）。
    exit /b 0
)
call :set_env_kv OLLAMA_MODEL %PICKED_MODEL%
echo [调整] .env 中的「%ENV_OLLAMA_MODEL%」本机未安装，已自动改用已有模型：%PICKED_MODEL%
exit /b 0

REM ---- 工具：停止占用指定端口的进程（重启服务用）
:kill_port
set "KPID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":%~1 "') do set "KPID=%%p"
if defined KPID (
    taskkill /f /t /pid %KPID% >nul 2>nul
    if errorlevel 1 (echo   端口 %~1 停止失败（进程 %KPID% 可能已退出）) else (echo   已停止端口 %~1（PID %KPID%）)
) else (
    echo   端口 %~1 上没有监听进程，跳过
)
REM 等待端口真正释放（旧进程退出后资源锁/端口可能仍有残留，最多等 6 秒）
set /a KP_WAIT=0
:kill_port_wait
call :port_busy %~1
if errorlevel 1 exit /b 0
call :sleep 1
set /a KP_WAIT+=1
if %KP_WAIT% LSS 6 goto :kill_port_wait
echo   [警告] 端口 %~1 等待 6 秒仍未释放，继续尝试启动
exit /b 0

REM ---- 工具：同 :url_ok，但用 localhost（兼容 Node 只绑 IPv6 回环的情况）
:url_ok_local
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://localhost:%~1%~2'; if('%~3' -eq '' -or $r.Content -match '%~3'){exit 0}else{exit 1}}catch{exit 1}" >nul 2>nul
exit /b %errorlevel%

REM ---- 工具：询问是否结束占用端口的进程（仅真实控制台可确认；非交互环境一律拒绝）
:offer_kill
set "KILLNOW="
call :stdin_is_console
if not "%IS_CONSOLE%"=="1" exit /b 1
echo        是否结束占用端口 %~1 的进程并继续？输入 Y 结束该进程，其他键取消。
set /p KILLNOW=请输入 Y 或直接回车取消：
if /i not "%KILLNOW%"=="Y" exit /b 1
call :kill_port %~1
exit /b 0

REM ---- 工具：探测 端口/路径 是否可访问且内容匹配标识（0=是，1=否）
:url_ok
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:%~1%~2'; if('%~3' -eq '' -or $r.Content -match '%~3'){exit 0}else{exit 1}}catch{exit 1}" >nul 2>nul
exit /b %errorlevel%

REM ---- 工具：端口是否被占用（0=被占用，1=空闲）
:port_busy
netstat -ano | findstr /c:"LISTENING" | findstr /c:":%~1 " >nul
exit /b %errorlevel%

REM ---- 工具：等待 N 秒（不依赖 timeout 命令，重定向/无控制台场景同样可用）
:sleep
set /a SLEEP_N=%~1+1
ping -n %SLEEP_N% 127.0.0.1 >nul
exit /b 0

REM ---- 工具：探测 Ollama 状态（running / installed / missing）
:ollama_check
set "OLLAMA_STATE=missing"
where ollama >nul 2>nul
if not errorlevel 1 set "OLLAMA_STATE=installed"
if "%OLLAMA_STATE%"=="missing" if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_STATE=installed"
if "%OLLAMA_STATE%"=="installed" (
    call :url_ok 11434 /api/version version
    if not errorlevel 1 set "OLLAMA_STATE=running"
)
exit /b 0

REM ---- 工具：查找可用的 Python 3.11+ 命令（%~1 [%~2] 为候选命令，如 python / py -3.12）
:try_python
%~1 %~2 -c "import sys;print('%%d.%%d' %% sys.version_info[:2]);sys.exit(0 if sys.version_info>=(3,11) else 1)" >"%TEMP%\_oc_pyver.txt" 2>nul
if errorlevel 1 exit /b 0
set "PYVERCAND="
set /p PYVERCAND=<"%TEMP%\_oc_pyver.txt"
if not defined PYVERCAND exit /b 0
set "BASEPY=%~1 %~2"
exit /b 0

REM ---- 工具：修改 backend\.env 中的键值（调用 scripts\apply_env_value.py）
:set_env_kv
"%VENV_PY%" "%ROOT%scripts\apply_env_value.py" %~1 %~2 --env "%BACKEND%\.env"
if errorlevel 1 (
    echo [警告] 写入 .env 失败，请在网页「模型设置」面板手动切换。
)
exit /b 0

REM ---- 工具：报告并校验 .env 配置（云端缺 Key 时可补填）
:env_report
"%VENV_PY%" "%ROOT%scripts\apply_env_value.py" --check --env "%BACKEND%\.env"
if not errorlevel 3 goto :env_report_done
echo [提醒] 云端模式尚未填写 LLM_API_KEY，生成解析时会报鉴权错误。
set /p FIXKEY=是否现在打开记事本补填？输入 Y 补填 / 其他键跳过：
if /i not "%FIXKEY%"=="Y" goto :env_report_done
notepad "%BACKEND%\.env"
"%VENV_PY%" "%ROOT%scripts\apply_env_value.py" --check --env "%BACKEND%\.env"
:env_report_done
exit /b 0

REM ---- 重启服务入口（交互输入 R 或命令行参数 restart 时跳转至此）
:restart_services
echo 正在停止旧服务（端口 8000 / 5173）...
call :kill_port 8000
call :kill_port 5173
call :sleep 2
set "BACK_UP=0"
set "FRONT_UP=0"
goto :start_services
