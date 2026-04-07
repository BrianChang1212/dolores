"""First-time setup: choose personality, pick model, import data, interactive Q&A."""

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .config import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_PIPER_VOICE,
    DEFAULT_TTS_BACKEND,
    get_personal_dir,
    get_personality_dir,
    load_config,
    save_config,
)
from .importer import scan_and_import

console = Console()


def _ollama_models_from_response(resp) -> list:
    """ollama.list() returns dict-like or ListResponse; models may be dict or Model."""
    if hasattr(resp, "get"):
        return resp.get("models") or []
    return getattr(resp, "models", None) or []


def _ollama_model_id(entry) -> str:
    """New ollama-py uses Model.model; older APIs used dict['name']."""
    if isinstance(entry, dict):
        return (entry.get("model") or entry.get("name") or "").strip()
    mid = getattr(entry, "model", None) or getattr(entry, "name", None)
    return str(mid).strip() if mid else ""


def _list_personalities() -> list[dict]:
    personas = []
    for yf in sorted(get_personality_dir().glob("*.yaml")):
        with open(yf, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["_file"] = yf.stem
        personas.append(data)
    return personas


def _check_ollama_models() -> list[str]:
    try:
        import ollama as ollama_client
        resp = ollama_client.list()
        models = _ollama_models_from_response(resp)
        return [n for m in models if (n := _ollama_model_id(m))]
    except Exception:
        return []


def run_onboarding() -> dict:
    """
    Interactive first-time setup.
    Returns a config dict to be saved.
    """
    console.print()
    console.print(Panel(
        "[bold magenta]Welcome to Dolores[/bold magenta]\n\n"
        "Let's set things up. This only takes a minute.",
        title="First Run Setup",
        border_style="bright_cyan",
    ))
    console.print()

    # --- 1. Choose personality ---
    personas = _list_personalities()
    table = Table(title="Available Companions", show_lines=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("Name", style="bold white")
    table.add_column("Archetype", style="magenta")
    table.add_column("Traits", style="dim")
    for i, p in enumerate(personas, 1):
        table.add_row(str(i), p.get("name", "?"), p.get("archetype", ""), p.get("traits", "")[:60])
    console.print(table)

    choice = Prompt.ask(
        "Choose your companion",
        choices=[str(i) for i in range(1, len(personas) + 1)],
        default="1",
    )
    selected_persona = personas[int(choice) - 1]
    persona_key = selected_persona["_file"]
    console.print(f"  [green]Selected:[/green] {selected_persona['name']} ({selected_persona['archetype']})\n")

    # --- 2. Choose Ollama model ---
    available_models = _check_ollama_models()
    if available_models:
        console.print("[bold]Ollama models found on your system:[/bold]")
        for i, m in enumerate(available_models, 1):
            console.print(f"  {i}. {m}")
        model_choice = Prompt.ask(
            "Pick a model (number or type name)",
            default="1",
        )
        try:
            idx = int(model_choice) - 1
            model = available_models[idx]
        except (ValueError, IndexError):
            model = model_choice
    else:
        console.print("[yellow]No Ollama models detected. Make sure Ollama is running.[/yellow]")
        model = Prompt.ask("Enter model name", default=DEFAULT_OLLAMA_MODEL)
    console.print(f"  [green]Model:[/green] {model}\n")

    # --- 3. Import personal data ---
    personal_dir = get_personal_dir()
    data_imported = False
    if personal_dir.is_dir() and any(personal_dir.iterdir()):
        files = [f.name for f in personal_dir.rglob("*") if f.is_file()]
        console.print(f"[bold]Found {len(files)} file(s) in [cyan]{personal_dir}[/cyan]:[/bold]")
        for fn in files[:10]:
            console.print(f"  • {fn}")
        if len(files) > 10:
            console.print(f"  ... and {len(files) - 10} more")

        do_import = Prompt.ask("Import these into memory?", choices=["y", "n"], default="y")
        if do_import.lower() == "y":
            console.print("[dim]Importing...[/dim]")
            results = scan_and_import(str(personal_dir), callback=lambda f, s: console.print(f"  {f}: {s}"))
            imported_count = sum(1 for r in results if r["status"] == "imported")
            console.print(f"  [green]Done![/green] Imported {imported_count} file(s).\n")
            data_imported = True
    else:
        console.print(
            f"[dim]No files in {personal_dir}.[/dim]\n"
            "  Tip: drop txt/md/pdf/docx/csv/xlsx/json/jsonl/images there; run [bold]/import[/bold] anytime.\n"
        )

    # --- 4. Interactive Q&A with the companion ---
    user_name = ""
    questions = selected_persona.get("onboarding_questions", [])
    greeting = selected_persona.get("onboarding_greeting", f"Hi! I'm {selected_persona['name']}.")

    console.print(Panel(
        f"[bold]{selected_persona['name']}[/bold]: {greeting}",
        border_style="magenta",
    ))

    qa_answers = []
    if questions:
        for q in questions:
            console.print(f"  [magenta]{selected_persona['name']}[/magenta]: {q}")
            answer = Prompt.ask("  You")
            qa_answers.append({"q": q, "a": answer})
            if not user_name and "名字" in q:
                user_name = answer.strip()

    if not user_name:
        user_name = Prompt.ask("What should I call you?", default="")

    # --- Build and save config ---
    cfg = load_config()
    cfg.update({
        "personality": persona_key,
        "ollama_model": model,
        "user_name": user_name,
        "voice_enabled": False,
        "tts_backend": DEFAULT_TTS_BACKEND,
        "piper_voice": selected_persona.get("piper_voice") or DEFAULT_PIPER_VOICE,
        "onboarding_done": True,
        "data_imported": data_imported,
        "onboarding_qa": qa_answers,
    })
    save_config(cfg)

    console.print()
    console.print(Panel(
        f"[green bold]Setup complete![/green bold]\n\n"
        f"Companion: {selected_persona['name']} | Model: {model}\n"
        f"Your name: {user_name or '(not set)'}\n\n"
        "Type anything to start chatting. Use [bold]/help[/bold] for commands.",
        border_style="bright_green",
    ))

    return cfg
