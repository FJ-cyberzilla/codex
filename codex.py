#!/usr/bin/env python3
"""
Cyberzilla™ Codex - Enterprise Edition v6.1.1
The ultimate production-ready tool with dynamic configuration, concurrency safety,
history tracking, and secure cleanup.
"""

import os
import sys
import subprocess
import json
import shutil
import time
import argparse
import threading
import concurrent.futures
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass, field

# --- 0. BANNER & UI ---

class Colors:
    """Cross-platform ANSI colors"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    PINK = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

    @staticmethod
    def symbol(success: bool) -> str:
        return f"{Colors.GREEN}✓{Colors.RESET}" if success else f"{Colors.RED}✗{Colors.RESET}"

def print_banner():
    """Displays the startup banner in pink"""
    banner = f"""{Colors.PINK}{Colors.BOLD}
╔══════════════════════════════════════════════════════╗
║                                                      ║
║   ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗         ║
║  ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝         ║
║  ██║     ██║   ██║██║  ██║█████╗   ╚███╔╝          ║
║  ██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗          ║
║  ╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗         ║
║   ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝         ║
║                                                      ║
║          Enterprise Code Analyzer & Quality Gate     ║
║                     Version 6.1.1                    ║
║                                                      ║
║  GitHub: FJ-cyberzilla                               ║
║  Status: Initiated  | Thread-Safe | Auto-Fix Enabled ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
{Colors.RESET}"""
    print(banner)

def print_menu():
    """Interactive menu for user selection"""
    menu = f"""
{Colors.PINK}╔════════════════════════════════════════════════════╗
║                      MAIN MENU                          ║
╠════════════════════════════════════════════════════╣
║                                                    ║
║  {Colors.CYAN}[1]{Colors.PINK} Analyze Code (Check Only)               ║
║  {Colors.CYAN}[2]{Colors.PINK} Analyze & Auto-Fix Issues               ║
║  {Colors.CYAN}[3]{Colors.PINK} View Analysis History                   ║
║  {Colors.CYAN}[4]{Colors.PINK} Cleanup Backup Files                    ║
║  {Colors.CYAN}[5]{Colors.PINK} Configuration Info                      ║
║  {Colors.CYAN}[0]{Colors.PINK} Exit                                    ║
║                                                    ║
╚════════════════════════════════════════════════════╝{Colors.RESET}
"""
    print(menu)

# --- 1. CONFIGURATION DATA STRUCTURES ---

@dataclass
class AppConfig:
    """Global Configuration loaded from external file"""
    fix_mode: bool = False
    verbose: bool = False
    max_workers: int = 4
    history_file: str = "codex_history.json"
    output_dir: str = "reports"
    default_timeout: int = 30
    # Common directories to always skip
    DEFAULT_SKIP = {
        'node_modules', 'venv', '.venv', '__pycache__', '.git',
        'build', 'dist', '.ipynb_checkpoints', 'site-packages'
    }
    skip_dirs: set = field(default_factory=set)

@dataclass
class AnalysisResult:
    """Holds the state of a single file analysis for reporting"""
    file_path: str
    language: str
    success: bool
    errors: List[str]
    warnings: List[str]
    was_fixed: bool = False

@dataclass
class RunSummary:
    """Summary of one single run for history tracking"""
    timestamp: str
    total_files: int
    passed: int
    failed: int
    fixed: int

# --- 2. CONFIGURATION & CONCURRENCY MANAGEMENT ---

class ConfigLoader:
    """Loads configuration from file with validation and provides robust defaults."""
    CONFIG_FILES = [Path(".codexrc.json"), Path("codex.json")]

    # Hardcoded Safe Defaults
    DEFAULT_TOOL_MAP = {
        'python': [
            {'tool': 'pylint', 'command': ['pylint', '--output-format=json', '--score=n'], 'check': True, 'fix': False, 'timeout': 30},
            {'tool': 'black', 'command': ['black', '-q'], 'check': False, 'fix': True, 'timeout': 30}
        ],
        'javascript': [
            {'tool': 'eslint', 'command': ['eslint', '--format=json'], 'check': True, 'fix': False, 'timeout': 30},
            {'tool': 'prettier', 'command': ['prettier', '--write'], 'check': False, 'fix': True, 'timeout': 30}
        ]
    }

    @staticmethod
    def _validate_tool_map(tool_map: dict) -> dict:
        """Enforces schema validation on loaded tool configuration."""
        valid_map = {}
        required_keys = ['tool', 'command', 'check', 'fix']

        for lang, tools in tool_map.items():
            if not isinstance(tools, list): continue

            valid_tools = []
            for tool_def in tools:
                if not all(k in tool_def for k in required_keys): continue
                valid_tools.append(tool_def)

            if valid_tools:
                valid_map[lang] = valid_tools
        return valid_map

    @staticmethod
    def load() -> Tuple['AppConfig', dict]:
        config_data = {}

        for file_path in ConfigLoader.CONFIG_FILES:
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        config_data.update(json.load(f))
                        print(f"{Colors.GREEN}[INFO] Loaded configuration from {file_path}.{Colors.RESET}")
                        break
                except Exception as e:
                    print(f"{Colors.RED}[ERROR] Failed to load {file_path}: {e}. Skipping.{Colors.RESET}")

        app_settings = config_data.get('app_settings', {})
        tool_map = config_data.get('language_tools', ConfigLoader.DEFAULT_TOOL_MAP)

        config = AppConfig(
            max_workers=app_settings.get('max_workers', 4),
            history_file=app_settings.get('history_file', 'codex_history.json'),
            output_dir=app_settings.get('output_dir', 'reports'),
            default_timeout=app_settings.get('default_timeout', 30),
            skip_dirs=set(app_settings.get('skip_dirs', [])) | AppConfig.DEFAULT_SKIP
        )

        return config, ConfigLoader._validate_tool_map(tool_map)

class ConcurrencyManager:
    """Manages file locks to prevent race conditions during fixing."""

    def __init__(self):
        self._locks = {}
        self._global_lock = threading.Lock()

    def get_lock(self, file_path: Path) -> threading.Lock:
        """Returns the specific lock for the given file path."""
        abs_path = str(file_path.resolve())
        with self._global_lock:
            if abs_path not in self._locks:
                self._locks[abs_path] = threading.Lock()
            return self._locks[abs_path]

# --- 3. CORE ANALYZER ---

class EnterpriseAnalyzer:
    def __init__(self, config: AppConfig, tool_map: dict):
        self.config = config
        self.tool_map = tool_map
        self.concurrency_manager = ConcurrencyManager()

        # Map file extensions to language keys defined in the config
        self.ext_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'javascript',
            '.go': 'go', '.rs': 'rust', '.c': 'c/c++', '.cpp': 'c/c++',
        }

    def _run_tool(self, file_path: Path, tool_config: dict, is_fixer: bool) -> Tuple[int, str, str]:
        """Executes a tool with backup/rollback safety for fixers."""
        cmd = tool_config['command'] + [str(file_path)]
        tool_name = tool_config['tool']
        timeout = tool_config.get('timeout', self.config.default_timeout)

        backup_path = file_path.with_suffix(f"{file_path.suffix}.codex.bak")

        try:
            if not shutil.which(cmd[0]):
                return -1, "", f"Tool '{cmd[0]}' not found in system path."

            if is_fixer:
                try:
                    shutil.copyfile(file_path, backup_path)
                except Exception: pass

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace',
                cwd=file_path.parent
            )

            if is_fixer and result.returncode != 0:
                if backup_path.exists():
                    shutil.move(backup_path, file_path)
                    return result.returncode, result.stdout, f"Fix failed; rolled back changes. {result.stderr}"

            if is_fixer and backup_path.exists():
                os.remove(backup_path)

            return result.returncode, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            if is_fixer and backup_path.exists():
                shutil.move(backup_path, file_path)
                return -2, "", f"Analysis timed out after {timeout}s and rolled back."
            return -2, "", f"Analysis timed out after {timeout}s."

        except Exception as e:
            if is_fixer and backup_path.exists():
                shutil.move(backup_path, file_path)
                return -3, "", f"Tool execution failed and rolled back: {e}"
            return -3, "", f"Tool execution failed: {e}"

    def process_file(self, file_path: Path) -> AnalysisResult:
        """The core pipeline: Fix (under lock) -> Check -> Result"""
        ext = file_path.suffix
        lang_key = self.ext_map.get(ext)

        if not lang_key or lang_key not in self.tool_map:
            return AnalysisResult(str(file_path), "Unknown", False, ["Unsupported language/extension"], [], False)

        # 1. Fixing Phase (Protected by Lock)
        was_fixed = False
        if self.config.fix_mode:
            file_lock = self.concurrency_manager.get_lock(file_path)
            with file_lock:
                for tool_config in self.tool_map.get(lang_key, []):
                    if tool_config.get('fix') and tool_config.get('command'):
                        if self._run_tool(file_path, tool_config, is_fixer=True)[0] == 0:
                            was_fixed = True
                            break

        # 2. Analysis Phase
        errors, warnings = [], []

        for tool_config in self.tool_map.get(lang_key, []):
            if tool_config.get('check') and tool_config.get('command'):
                tool_name = tool_config['tool']
                code, out, err = self._run_tool(file_path, tool_config, is_fixer=False)

                if code == -1:
                    warnings.append(f"{tool_name} not available. Install it.")
                elif code != 0 or err:
                    output_lines = (out + err).splitlines()

                    if not output_lines:
                        errors.append(f"Exit code {code} from {tool_name}")
                    else:
                        errors.extend([f"[{tool_name}] {line}" for line in output_lines[:5]])

        success = not errors
        return AnalysisResult(str(file_path), lang_key.capitalize(), success, errors, warnings, was_fixed)

    def scan_directory(self, path: str) -> List[AnalysisResult]:
        """Threaded directory scanning and file finding"""
        target = Path(path)
        files_to_scan = []

        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in self.config.skip_dirs]
            for f in files:
                if Path(f).suffix in self.ext_map:
                    files_to_scan.append(Path(root) / f)

        print(f"{Colors.CYAN}Found {len(files_to_scan)} files. Starting analysis...{Colors.RESET}")

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = {executor.submit(self.process_file, f): f for f in files_to_scan}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                if self.config.verbose:
                    status = "✓" if result.success else "✗"
                    print(f"{status} {result.file_path}")
                else:
                    print(".", end="", flush=True)

        print("\n")
        return results

# --- 4. REPORTING & HISTORY ---

class HistoryManager:
    """Handles reading and writing the history log"""

    def __init__(self, history_file: str):
        self.HISTORY_FILE = Path(history_file)

    def load(self) -> List[RunSummary]:
        if not self.HISTORY_FILE.exists(): return []
        try:
            with open(self.HISTORY_FILE, 'r') as f:
                data = json.load(f)
                return [RunSummary(**d) for d in data]
        except Exception:
            return []

    def save(self, history: List[RunSummary]):
        history_data = [d.__dict__ for d in history]
        try:
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(history_data, f, indent=4)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to save history: {e}{Colors.RESET}")

    def display_history(self):
        """Shows formatted history"""
        history = self.load()
        if not history:
            print(f"{Colors.YELLOW}No analysis history found.{Colors.RESET}")
            return

        print(f"\n{Colors.PINK}{'='*70}")
        print(f"{Colors.BOLD}   ANALYSIS HISTORY (Last 10 Runs){Colors.RESET}")
        print(f"{Colors.PINK}{'='*70}{Colors.RESET}")
        print(f"{'TIMESTAMP':<20} | {'TOTAL':<6} | {'PASS':<5} | {'FAIL':<5} | {'FIXED':<6}")
        print("-" * 70)

        for run in history[-10:]:
            print(f"{run.timestamp:<20} | {run.total_files:<6} | {run.passed:<5} | {run.failed:<5} | {run.fixed:<6}")
        print(f"{Colors.PINK}{'='*70}{Colors.RESET}\n")


def generate_report(results: List[AnalysisResult], config: AppConfig) -> RunSummary:
    """Generates the final table and exports to JSON."""

    total = len(results)
    passed = sum(1 for r in results if r.success)
    fixed = sum(1 for r in results if r.was_fixed)
    failed = total - passed

    print("\n" + "="*70)
    print(f"{Colors.BOLD}   CYBERZILLA CODEX - FINAL REPORT   {Colors.RESET}")
    print("="*70)
    print(f"{Colors.BOLD}{'STATUS':<8} | {'TYPE':<10} | {'FILE':<30} | {'DETAILS'}{Colors.RESET}")
    print("-" * 70)

    for r in results:
        status_icon = Colors.symbol(r.success)
        fix_icon = "🔧" if r.was_fixed else " "

        fname = r.file_path
        if len(fname) > 30: fname = "..." + fname[-27:]

        info = f"{len(r.errors)} Err" if not r.success else "OK"
        if r.was_fixed: info += " (Fixed)"

        print(f"   {status_icon} {fix_icon}  | {r.language:<10} | {fname:<30} | {info}")

        if not r.success and len(r.errors) > 0:
            for e in r.errors[:3]:
                print(f"         {Colors.RED}└─ {e}{Colors.RESET}")

    print("-" * 70)
    print(f"Files: {total} | {Colors.GREEN}Passed: {passed}{Colors.RESET} | {Colors.RED}Failed: {failed}{Colors.RESET} | {Colors.YELLOW}Auto-Fixed: {fixed}{Colors.RESET}")

    if failed > 0:
        print(f"\n{Colors.RED}[!] MERGE BLOCKED: Fix {failed} failed files to pass the Quality Gate.{Colors.RESET}")

    # Export to JSON
    output_path = Path(config.output_dir)
    output_path.mkdir(exist_ok=True)

    json_data = [r.__dict__ for r in results]
    json_file = output_path / f"codex_report_{time.time():.0f}.json"

    try:
        with open(json_file, 'w') as f:
            json.dump(json_data, f, indent=4)
        print(f"\n{Colors.CYAN}Exported detailed report to: {json_file.resolve()}{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to export JSON report: {e}{Colors.RESET}")

    return RunSummary(
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        total_files=total,
        passed=passed,
        failed=failed,
        fixed=fixed
    )

def compare_and_update_history(current_summary: RunSummary, history_file: str):
    """Compares current run to the last run and updates history."""

    manager = HistoryManager(history_file)
    history = manager.load()

    print("\n" + "="*70)
    print(f"{Colors.BOLD}   CODE QUALITY TREND ANALYSIS   {Colors.RESET}")
    print("="*70)

    if history:
        last_run = history[-1]
        diff_failed = current_summary.failed - last_run.failed

        trend_icon = "⬆️" if diff_failed < 0 else ("⬇️" if diff_failed > 0 else "=")
        trend_color = Colors.GREEN if diff_failed < 0 else (Colors.RED if diff_failed > 0 else Colors.YELLOW)
        trend_message = ("Quality improved! Fewer failed files." if diff_failed < 0
                         else ("Quality degraded. More failed files." if diff_failed > 0
                         else "Quality remained stable."))

        print(f"Last Scan ({last_run.timestamp}): Failed Files: {last_run.failed}")
        print(f"Current Scan ({current_summary.timestamp}): Failed Files: {current_summary.failed}")
        print(f"\n{trend_color}{Colors.BOLD}{trend_icon}  Trend: {trend_message} ({abs(diff_failed)} change){Colors.RESET}")
    else:
        print(f"{Colors.CYAN}No previous history found. Creating baseline.{Colors.RESET}")

    history.append(current_summary)
    manager.save(history)

def cleanup_backups(path: str):
    """Deletes any orphaned .codex.bak files left by a crashed run."""
    target = Path(path)
    count = 0
    for root, _, files in os.walk(target):
        for f in files:
            if f.endswith(".codex.bak"):
                try:
                    os.remove(Path(root) / f)
                    count += 1
                except Exception: pass
    if count > 0:
        print(f"{Colors.YELLOW}[CLEANUP] Removed {count} orphaned backup files.{Colors.RESET}")
    else:
        print(f"{Colors.GREEN}[CLEANUP] No orphaned backup files found.{Colors.RESET}")

def show_config_info(config: AppConfig, tool_map: dict):
    """Display current configuration"""
    print(f"\n{Colors.PINK}{'='*70}")
    print(f"{Colors.BOLD}   CURRENT CONFIGURATION{Colors.RESET}")
    print(f"{Colors.PINK}{'='*70}{Colors.RESET}")
    print(f"Max Workers: {config.max_workers}")
    print(f"History File: {config.history_file}")
    print(f"Output Directory: {config.output_dir}")
    print(f"Default Timeout: {config.default_timeout}s")
    print(f"Skip Directories: {', '.join(config.skip_dirs)}")
    print(f"\nSupported Languages: {', '.join(tool_map.keys())}")
    print(f"{Colors.PINK}{'='*70}{Colors.RESET}\n")

# --- 5. MAIN APPLICATION LOGIC ---

def run_analysis(target_path: str, fix_mode: bool = False, verbose: bool = False) -> bool:
    """Main analysis runner function"""
    try:
        config, tool_map = ConfigLoader.load()
        config.fix_mode = fix_mode
        config.verbose = verbose

        analyzer = EnterpriseAnalyzer(config, tool_map)
        results = analyzer.scan_directory(target_path)
        summary = generate_report(results, config)
        compare_and_update_history(summary, config.history_file)

        return summary.failed == 0

    except Exception as e:
        print(f"{Colors.RED}[FATAL] Analysis failed: {e}{Colors.RESET}")
        return False

def interactive_mode():
    """Interactive command line interface"""
    print_banner()
    
    while True:
        print_menu()
        choice = input(f"{Colors.CYAN}Select an option [0-5]: {Colors.RESET}").strip()
        
        if choice == '1':
            path = input(f"{Colors.CYAN}Enter path to analyze [.]: {Colors.RESET}").strip() or "."
            run_analysis(path, fix_mode=False, verbose=True)
            
        elif choice == '2':
            path = input(f"{Colors.CYAN}Enter path to analyze [.]: {Colors.RESET}").strip() or "."
            run_analysis(path, fix_mode=True, verbose=True)
            
        elif choice == '3':
            config, _ = ConfigLoader.load()
            HistoryManager(config.history_file).display_history()
            
        elif choice == '4':
            path = input(f"{Colors.CYAN}Enter path to clean [.]: {Colors.RESET}").strip() or "."
            cleanup_backups(path)
            
        elif choice == '5':
            config, tool_map = ConfigLoader.load()
            show_config_info(config, tool_map)
            
        elif choice == '0':
            print(f"{Colors.PINK}Thank you for using Cyberzilla Codex!{Colors.RESET}")
            break
            
        else:
            print(f"{Colors.RED}Invalid option. Please try again.{Colors.RESET}")

def main():
    """Main entry point with CLI argument support"""
    parser = argparse.ArgumentParser(description="Cyberzilla Codex - Enterprise Code Quality Analyzer")
    parser.add_argument("path", nargs="?", default=".", help="Target directory to analyze")
    parser.add_argument("--fix", action="store_true", help="Enable auto-fix mode")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive mode")
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_mode()
    else:
        success = run_analysis(args.path, args.fix, args.verbose)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
