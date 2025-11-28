"""Output formatting utilities with optional rich support."""

from typing import Optional

try:
    from rich.console import Console

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Global console instance
_console: Optional["Console"] = None


def get_console() -> "Console":
    """Get or create the global rich console."""
    global _console
    if _console is None:
        if RICH_AVAILABLE:
            _console = Console()
        else:
            _console = FallbackConsole()
    return _console


class FallbackConsole:
    """Fallback console when rich is not available."""

    def print(self, *args, **kwargs) -> None:  # type: ignore
        """Print to stdout."""
        # Strip rich markup for plain output
        if args:
            text = str(args[0])
            # Simple markup removal (strip [style] tags)
            import re

            text = re.sub(r"\[.*?\]", "", text)
            print(text)
        else:
            print(*args)

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        print(f"\n{'=' * 60}")
        if title:
            print(f" {title}")
            print("=" * 60)


def print_success(message: str) -> None:
    """Print a success message.

    Args:
        message: Message to print
    """
    console = get_console()
    if RICH_AVAILABLE:
        console.print(f"✓ {message}", style="green bold")
    else:
        print(f"✓ {message}")


def print_error(message: str) -> None:
    """Print an error message.

    Args:
        message: Message to print
    """
    console = get_console()
    if RICH_AVAILABLE:
        console.print(f"✗ {message}", style="red bold")
    else:
        print(f"✗ {message}")


def print_warning(message: str) -> None:
    """Print a warning message.

    Args:
        message: Message to print
    """
    console = get_console()
    if RICH_AVAILABLE:
        console.print(f"⚠ {message}", style="yellow bold")
    else:
        print(f"⚠ {message}")


def print_section(title: str) -> None:
    """Print a section divider.

    Args:
        title: Section title
    """
    console = get_console()
    if RICH_AVAILABLE:
        console.rule(f"[bold]{title}[/bold]")
    else:
        console.rule(title)
