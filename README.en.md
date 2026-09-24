# Codex Model Monitor

<img src="web/logo.png" alt="codexMonitor logo" width="128" height="128">

English | [简体中文](README.md)

Compare the model requested by Codex with the model declared by the server in a local web interface. An internal probe collects model metadata while Codex connects directly to the service; no proxy or certificate installation is required. This directory is self-contained and does not depend on custom timezone or theme launchers.

## Installation

Currently supported: **Windows x64 with the official Codex desktop package (`OpenAI.Codex`)**.

1. Install the official Codex desktop app and sign in.
2. Install PowerShell **7.4+**, Python **3.10+**, Git, and Rust through rustup. Make sure `pwsh`, `python`, `git`, and `cargo` are available in your terminal.
3. Install Visual Studio Build Tools with the **Desktop development with C++** workload, including the MSVC x64 build tools and Windows SDK.
4. Save this directory to a writable local location. The first build requires internet access, sufficient disk space, and time to compile. The matching official source specifies the Rust toolchain version.
5. Open **Edit environment variables for your account** in Windows. Add the full path of the folder containing `codex-monitor.cmd` to your user `Path` variable, keeping the existing entries. Add the folder path, not the file path. Save your changes and open a new terminal. You can then run `codex-monitor` from any directory. If another command with the same name is installed, resolve that conflict so the command uses this launcher.

No pip or npm installation is required. The distribution does not include a prebuilt backend, account data, or runtime logs.

## Usage

After configuring PATH, completely exit Codex, including any system tray process. Run this command from any directory:

```powershell
codex-monitor -Desktop
```

The launcher checks the backend version bundled with your desktop app. If no matching cache exists, the terminal displays `Building probe backend ...`, downloads the matching official source, applies the probe, and compiles it. Once the build succeeds, it launches the standard Codex interface and the monitor webpage. The launcher does not change your timezone, theme, official installation files, or user environment variables. Subsequent launches reuse a matching cache; a desktop backend version change triggers a new build.

The default webpage is `http://127.0.0.1:8765/` and refreshes every two seconds. Use the language control to switch between English and Chinese.

```powershell
# View existing logs without launching or modifying a running Codex instance
codex-monitor

# Use a different port without opening the browser automatically
codex-monitor -Desktop -Port 8766 -NoBrowser
```

If PowerShell execution policy blocks downloaded scripts, review the files first and unblock them in accordance with your machine or organization's policy.

Press `Ctrl+C` to stop the web server; Codex runs independently. To return to the standard backend, completely exit the monitored Codex instance, then launch Codex through its official shortcut. A normal launch does not generate new probe records.

## Important notes

Run `codex-monitor -Cache` to open the terminal cache settings. Enter `K` to keep compilation caches for faster updates, `R` to remove them (the default), or `C` to cancel. After choosing removal, enter `N` to delete existing compilation caches now or `L` to defer cleanup until the next successful build or backend reuse. Runnable backends, the source repository, and call logs are preserved. Stop any build before immediate cleanup.

The preference is saved in `.monitor-settings.json` in the project root and ignored by Git. Choosing Keep disables the automatic compilation-cache cleanup described below. Use `-Cache` separately; it does not launch Codex or the webpage.

- The monitor compares the requested model name with the server's `response.model`, falling back to the `openai-model` response header. This is not proof of the model weights actually used by the server. Different names alone do not prove a downgrade. If either model is missing, the status is unknown.
- Call purposes are classified using local task and turn metadata. Categories include main tasks, forked conversations, subagents, and background helpers. Calls remain unknown when there is insufficient evidence. Changes to official log formats may affect classification.
- Logs stay in this directory under `logs/`. Daily SQLite archives contain only the requested model, response model, timestamp, consistency status, and purpose. Raw probe records also contain task, turn, and call identifiers for correlation. They do not record prompts, response text, or authentication tokens. Reading official metadata does not modify `.codex`.
- Daily archives use **UTC+8** and retain the latest **15 dates with records**, removing the oldest dates first. The webpage displays timestamps in the browser's local timezone, so displayed dates may differ from archive filenames.
- `output/probes/` retains one runnable probe backend version. The old cache is replaced only after a new build succeeds. After a successful build or verification of a reusable backend, the launcher removes compilation caches in `output/target/` and the legacy `upstream/codex-rs/target/`, keeping the runnable backend. The next update requires a full rebuild and may take longer. Failed builds retain their compilation caches. Exit the monitored Codex instance and the monitor before manually cleaning generated files.
- Startup stops if the matching official source is unavailable, the patch is incompatible, or the build fails. It does not launch a mismatched older backend. Check the terminal error before retrying. The `-monitor` suffix in startup messages is a display label only; it does not change the embedded version or authentication fields.
- The web server listens only on the local loopback address. Do not forward its port to the public internet. Exclude `logs/`, `output/`, and `upstream/` when sharing the project; these directories are already covered by `.gitignore`.
- This is an unofficial local modification. Compatibility with future desktop versions is not guaranteed. Do not switch backends while tasks are still running.

## Source checks

Run these commands from the project directory:

```powershell
python -B -m unittest test_monitor.py
pwsh -NoProfile -File .\test_build_probe.ps1
```

The second command requires Codex to be installed. It creates a version-check copy under `output/desktop/`, but does not build the probe or launch the desktop app.
