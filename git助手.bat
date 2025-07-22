@echo off
rem 设置控制台编码为UTF-8，支持中文显示
chcp 65001 > nul

rem 对于Windows 10 1809之前的版本，可能需要将文件编码改为ANSI，并注释掉chcp 65001。
rem.

:init
cls
title Git 助手 (InstantAudioPreviewer)

setlocal EnableDelayedExpansion

REM --- 配置 ---
REM 设置你的Gitee仓库URL (硬编码)
set GITEE_REPO_URL=https://gitee.com/wangru2025/instant-audio-previewer.git
REM 设置你的远程仓库名称，通常是 origin
set REMOTE_NAME=origin
REM 设置你的默认分支名，通常是 master 或 main
set DEFAULT_BRANCH=master
REM ----------------

REM --- 检查 Git 是否可用 ---
git --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo 错误：Git未安装或未在系统PATH中找到。请先安装Git。
    echo.
    pause>nul
    goto :eof
)

REM --- 检查当前目录是否是Git仓库 ---
if not exist .git (
    echo.
    echo 错误：当前目录不是一个Git仓库。
    echo 请先执行 "git init" 或者 "git clone %GITEE_REPO_URL%" 来初始化或克隆一个仓库。
    echo.
    pause>nul
    goto :eof
)

REM --- 检查远程仓库是否配置 ---
git remote -v > nul 2>&1
if errorlevel 1 (
    echo.
    echo 警告：未检测到有效的远程仓库。
    echo 尝试关联 Gitee 仓库: %GITEE_REPO_URL%
    git remote add origin "%GITEE_REPO_URL%"
    if errorlevel 1 (
        echo.
        echo 错误：关联远程仓库失败。请检查URL或你的网络连接。
        echo.
        pause>nul
        goto :eof
    ) else (
        echo.
        echo 远程仓库已成功关联。
        echo.
    )
) else (
    echo.
    echo 远程仓库已配置:
    git remote -v
    echo.
)

REM --- 确认当前分支 ---
for /f "tokens=*" %%a in ('git branch --show-current 2^>nul') do set CURRENT_BRANCH=%%a
if "%CURRENT_BRANCH%"=="" set CURRENT_BRANCH=%DEFAULT_BRANCH% REM 如果获取分支失败，使用默认值

echo.
echo ===================================
echo   Git 助手 (InstantAudioPreviewer)
echo ===================================
echo.
echo 当前分支: !CURRENT_BRANCH!
echo 远程仓库: !REMOTE_NAME!
echo.
pause>nul
goto :menu

:menu
cls
echo.
echo 请选择你想要执行的操作：
echo -----------------------------
echo 1. 查看状态 (git status)
echo 2. 拉取最新内容 (git pull)
echo 3. 添加所有改动到暂存区 (git add .)
echo 4. 提交改动 (git commit)
echo 5. 推送改动 (git push)
echo 6. 查看提交历史 (git log)
echo 7. 创建新分支 (git branch)
echo 8. 切换分支 (git checkout)
echo -----------------------------
echo 9. 退出
echo -----------------------------
echo.
choice /M "请输入选项数字" /C 123456789 /N
set choice=!errorlevel!

REM --- 处理用户选择 ---
if !choice! equ 1 goto :view_status
if !choice! equ 2 goto :pull_latest
if !choice! equ 3 goto :add_all
if !choice! equ 4 goto :commit_changes
if !choice! equ 5 goto :push_changes
if !choice! equ 6 goto :view_log
if !choice! equ 7 goto :create_branch
if !choice! equ 8 goto :checkout_branch
if !choice! equ 9 goto :eof

rem 实际上 choice 命令自带了无效选项的错误处理，不会到达这里

rem --- 各功能实现 ---

:view_status
cls
echo.
echo --- 执行: git status ---
git status
echo.
pause>nul
goto :menu

:pull_latest
cls
echo.
echo --- 执行: git pull ---
REM 尝试使用默认远程仓库和分支进行拉取
REM Git 会自动处理身份验证（SSH密钥或HTTPS凭据）
git pull !REMOTE_NAME! !DEFAULT_BRANCH!
echo.
pause>nul
goto :menu

:add_all
cls
echo.
echo --- 执行: git add . ---
REM 检查是否有未跟踪的文件或修改，提示用户
git status | findstr /C:"Changes not staged for commit" > nul || git status | findstr /C:"Untracked files" > nul
if errorlevel 0 (
    echo 发现需要添加到暂存区的改动。
) else (
    echo 没有需要添加到暂存区的改动。
    pause>nul
    goto :menu
)

REM 检查是否存在 .gitignore 文件，如果不存在，提示用户创建
if not exist .gitignore (
    echo.
    echo 警告：未找到 .gitignore 文件。
    echo 建议创建一个 .gitignore 文件来忽略不必要的文件（如 .venv/, __pycache__/ 等）。
    echo.
    pause>nul
)
git add .
echo 所有改动和新文件已添加到暂存区。
echo.
pause>nul
goto :menu

:commit_changes
cls
echo.
echo --- 执行: git commit ---
REM 检查是否有暂存的改动
git diff --cached --quiet
if errorlevel 0 (
    echo 错误：没有找到任何已暂存的改动。请先执行 'git add'。
    pause>nul
    goto :menu
)

echo.
set /p commit_message="请输入提交信息 (例如: Feat: Add packaging spec file): "
if "!commit_message!"=="" (
    echo 提交信息不能为空。
    pause>nul
    goto :commit_changes
)

REM 执行 commit
git commit -m "!commit_message!"
echo.
echo 改动已提交到本地仓库。
echo.
pause>nul
goto :menu

:push_changes
cls
echo.
echo --- 执行: git push ---
REM 检查是否有本地提交但未推送到远程
git rev-list --count !REMOTE_NAME!/!DEFAULT_BRANCH!..HEAD > push_check.tmp
set /p ahead_count=<push_check.tmp
del push_check.tmp

if "!ahead_count!"=="0" (
    echo 没有本地提交需要推送。
) else (
    echo 发现 !ahead_count! 个本地提交未推送。
    REM Git 会自动处理身份验证（SSH密钥或HTTPS凭据）
    git push !REMOTE_NAME! !DEFAULT_BRANCH!
    echo.
    echo 推送完成。
)
echo.
pause>nul
goto :menu

:view_log
cls
echo.
echo --- 执行: git log ---
REM 使用 --oneline --graph --decorate --all 更加直观
git log --oneline --graph --decorate --all
echo.
pause>nul
goto :menu

:create_branch
cls
echo.
echo --- 创建新分支 ---
echo.
set /p new_branch_name="请输入新分支的名称 (例如: feature/new-label-management): "
if "!new_branch_name!"=="" (
    echo 分支名称不能为空。
    pause>nul
    goto :create_branch
)
REM 检查分支是否已存在
git show-ref --verify --quiet refs/heads/!new_branch_name!
if errorlevel 1 (
    git branch "!new_branch_name!"
    echo 分支 "!new_branch_name!" 已创建。
) else (
    echo 分支 "!new_branch_name!" 已存在。
)
echo.
pause>nul
goto :menu

:checkout_branch
cls
echo.
echo --- 切换分支 ---
echo.
set /p branch_to_checkout="请输入要切换到的分支名称 (例如: master, main, feature/login): "
if "!branch_to_checkout!"=="" (
    echo 分支名称不能为空。
    pause>nul
    goto :checkout_branch
)
REM 检查分支是否存在
git show-ref --verify --quiet refs/heads/!branch_to_checkout!
if errorlevel 1 (
    echo 分支 "!branch_to_checkout!" 不存在。
) else (
    REM 切换分支
    git checkout "!branch_to_checkout!"
    echo 已切换到分支 "!branch_to_checkout!"。
    REM 确保当前分支的本地跟踪与远程分支匹配（如果远程有同名分支）
    git branch --set-upstream-to=!REMOTE_NAME!/!branch_to_checkout! "!branch_to_checkout!" >nul 2>&1
    REM 如果切换到新分支，且远程存在同名分支，尝试拉取
    git pull !REMOTE_NAME! "!branch_to_checkout!" >nul 2>&1
)
echo.
pause>nul
goto :menu

REM --- 退出 ---
:eof
echo.
echo 退出 Git 助手。
pause>nul
endlocal
exit /b