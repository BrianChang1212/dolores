"""CLI dialogue loop — Logo, status bar, chat, commands, voice integration."""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .chat_engine import ChatEngine
from .config import (
    DEFAULT_TTS_BACKEND,
    get_personal_dir,
    is_first_run,
    load_config,
    save_config,
)
from .importer import scan_and_import
from .onboarding import (
    _ollama_model_id,
    _ollama_models_from_response,
    run_onboarding,
)

console = Console()


LOGO = r"""
[bright_cyan]
 ╔══════════════════════════════════════════════════════════════╗
 ║                              ◯                               ║
 ║                             ╱ ╲                              ║
 ║                            ╱   ╲                             ║
 ║                                                              ║
 ║   ██████╗  ██████╗ ██╗      ██████╗ ██████╗ ███████╗███████╗ ║
 ║   ██╔══██╗██╔═══██╗██║     ██╔═══██╗██╔══██╗██╔════╝██╔════╝ ║
 ║   ██║  ██║██║   ██║██║     ██║   ██║██████╔╝█████╗  ███████╗ ║
 ║   ██║  ██║██║   ██║██║     ██║   ██║██╔══██╗██╔══╝  ╚════██║ ║
 ║   ██████╔╝╚██████╔╝███████╗╚██████╔╝██║  ██║███████╗███████║ ║
 ║   ╚═════╝  ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝ ║
 ║                                                              ║
 ║                            ╲   ╱                             ║
 ║                             ╲ ╱                              ║
 ║                              ◯                               ║
 ║                                                              ║
 ║   [dim italic]"I remember you. I remember everything about you."[/dim italic]      ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝
[/bright_cyan]"""


HELP_TEXT = """
[bold cyan]Commands:[/bold cyan]
  [bold]/help[/bold]     — Show this help
  [bold]/status[/bold]   — Show companion status & system info
  [bold]/voice[/bold]    — Toggle voice output on/off
  [bold]/tts[/bold]      — Choose TTS engine: piper or edge
  [bold]/voices[/bold]   — Pick Piper or Edge voice (saved in config)
  [bold]/model[/bold]    — Switch Ollama model
  [bold]/import[/bold]   — Import files from personal/ folder
  [bold]/persona[/bold]  — Switch personality
  [bold]/quit[/bold]     — Exit Dolores
  [dim](aliases: /exit /q · /h · /voicepick)[/dim]
"""


def _print_startup_panel(engine: ChatEngine):
    """Print the full SYSTEM + COMPANION startup panel."""
    cfg = load_config()
    name = engine.get_companion_name()
    emo = engine.emotion
    drawers = engine.get_drawer_count()
    
    voice_status = "ON" if cfg.get("voice_enabled") else "OFF"
    tts_backend = cfg.get("tts_backend", DEFAULT_TTS_BACKEND)
    model_name = engine.model
    
    mood_display = emo.get_mood_display()
    affection_bar = emo.get_affection_bar(width=10)
    affection_pct = emo.affection
    total_convos = emo.total_conversations
    
    panel_text = f"""[bold cyan]─────────────── [ SYSTEM ] ─────────────────[/bold cyan]

  ◈ Core......... mempalace
  ◈ Engine....... Ollama ({model_name})
  ◈ Voice........ {voice_status} ({tts_backend})
  ◈ Memories..... {drawers} drawers loaded

[bold magenta]──────────── [ ♡ COMPANION ] ───────────────[/bold magenta]

  ♡ Name......... {name}
  ♡ Mood......... {mood_display}
  ♡ Affection.... {affection_bar} {affection_pct}%
  ♡ Together..... {total_convos} conversations
  ♡ Status....... [green]♡ Online[/green]

[dim italic]Your AI Companion · She remembers, she cares.[/dim italic]
"""
    console.print(Panel(panel_text, border_style="bright_cyan", padding=(0, 2)))


def _print_status_bar(engine: ChatEngine):
    """Print a compact status bar."""
    name = engine.get_companion_name()
    mood_display = engine.emotion.get_mood_display()
    affection_bar = engine.emotion.get_affection_bar()
    cfg = load_config()
    voice = "ON" if cfg.get("voice_enabled") else "OFF"
    if cfg.get("voice_enabled"):
        voice += f" [{cfg.get('tts_backend', DEFAULT_TTS_BACKEND)}]"

    table = Table.grid(padding=(0, 2))
    table.add_row(
        f"[bold magenta]{name}[/bold magenta]",
        f"Mood: {mood_display}",
        f"Affection: {affection_bar}",
        f"Voice: [{'green' if cfg.get('voice_enabled') else 'red'}]{voice}[/]",
        f"Model: [dim]{engine.model}[/dim]",
    )
    console.print(table)
    console.print("[dim]─" * min(console.width, 80) + "[/dim]")


def _handle_status(engine: ChatEngine):
    name = engine.get_companion_name()
    emo = engine.emotion
    cfg = load_config()
    drawers = engine.get_drawer_count()

    if cfg.get("voice_enabled"):
        vinfo = f"ON — backend: {cfg.get('tts_backend', DEFAULT_TTS_BACKEND)}"
        if cfg.get("tts_backend") == "piper":
            from .voice import default_piper_voice
            vinfo += f" — voice: {cfg.get('piper_voice', default_piper_voice())}"
    else:
        vinfo = "OFF"

    panel_text = (
        f"[bold]Companion:[/bold] {name}\n"
        f"[bold]Mood:[/bold] {emo.get_mood_display()}\n"
        f"[bold]Affection:[/bold] {emo.get_affection_bar(width=20)} ({emo.affection}/100)\n"
        f"[bold]Level:[/bold] {emo.get_affection_level()}\n"
        f"[bold]Total chats:[/bold] {emo.total_conversations}\n"
        f"[bold]First met:[/bold] {emo.first_met or 'N/A'}\n"
        f"[bold]Memory drawers:[/bold] {drawers}\n"
        f"[bold]Model:[/bold] {engine.model}\n"
        f"[bold]Voice:[/bold] {vinfo}\n"
        f"[bold]User:[/bold] {cfg.get('user_name', 'N/A')}"
    )
    console.print(Panel(panel_text, title="Status", border_style="cyan"))


def _handle_voice(engine: ChatEngine):
    cfg = load_config()
    enabled = not cfg.get("voice_enabled", False)
    cfg["voice_enabled"] = enabled
    save_config(cfg)
    state = "[green]ON[/green]" if enabled else "[red]OFF[/red]"
    console.print(f"  Voice output: {state}")


def _handle_tts():
    from .voice import default_piper_voice, piper_available

    cfg = load_config()
    cur = cfg.get("tts_backend", DEFAULT_TTS_BACKEND)
    if cur not in ("edge", "piper"):
        cur = DEFAULT_TTS_BACKEND
    console.print(f"  Current TTS: [cyan]{cur}[/cyan]")
    console.print("  [dim]piper — Piper local ONNX (default; first run downloads model)[/dim]")
    console.print("  [dim]edge  — Microsoft Edge neural TTS (needs internet)[/dim]")
    if not piper_available():
        console.print(
            "  [yellow]Piper not installed:[/yellow] pip install piper-tts"
        )
    choice = Prompt.ask("Select backend", choices=["piper", "edge"], default=cur)
    cfg["tts_backend"] = choice
    if choice == "piper":
        default_v = cfg.get("piper_voice") or default_piper_voice()
        nv = Prompt.ask(
            "Piper voice id (e.g. zh_CN-huayan-medium, en_US-lessac-medium)",
            default=default_v,
        )
        cfg["piper_voice"] = nv.strip()
        console.print(
            "  [dim]Voice files: ~/.dolores/piper_voices/  (auto-download on first speak)[/dim]"
        )
    save_config(cfg)
    console.print(f"  [green]TTS backend: {choice}[/green]")


def _handle_voices(engine: ChatEngine):
    from .voice import (
        CURATED_PIPER_VOICES,
        clear_piper_voice_cache,
        default_piper_voice,
        fetch_edge_voices,
        fetch_piper_voice_ids,
    )

    cfg = load_config()
    persona = engine.persona
    cur_p = cfg.get("piper_voice") or persona.get("piper_voice") or default_piper_voice()
    cur_e = cfg.get("edge_voice") or persona.get("tts_voice", "zh-TW-HsiaoChenNeural")

    console.print(
        f"  [bold]Current[/bold]  Piper: [cyan]{cur_p}[/cyan]  |  Edge: [cyan]{cur_e}[/cyan]"
    )
    console.print(
        "  [dim]Overrides ~/.dolores/config.json — [bold]reset[/bold] clears and uses persona YAML.[/dim]"
    )
    action = Prompt.ask(
        "Action",
        choices=["piper", "edge", "reset", "cancel"],
        default="piper",
    )
    if action == "cancel":
        return
    if action == "reset":
        cfg.pop("piper_voice", None)
        cfg.pop("edge_voice", None)
        save_config(cfg)
        clear_piper_voice_cache()
        console.print("  [green]Voice overrides cleared (persona defaults).[/green]")
        return

    if action == "piper":
        cat = Prompt.ask(
            "Voice list",
            choices=["zh_CN", "en_US", "en_GB", "curated"],
            default="zh_CN",
        )
        if cat == "curated":
            voices = list(CURATED_PIPER_VOICES)
        else:
            voices = fetch_piper_voice_ids(cat)
        if not voices:
            console.print("[yellow]No voices; check network or try 'curated'.[/yellow]")
            return
        max_show = 40
        show = voices[:max_show]
        for i, v in enumerate(show, 1):
            mark = "  <- current" if v == cur_p else ""
            console.print(f"    {i:2}. {v}{mark}")
        if len(voices) > max_show:
            console.print(f"    [dim]... {len(voices) - max_show} more (narrow with /voices + filter)[/dim]")
        pick = Prompt.ask(
            f"Number 1-{len(show)} or paste full voice id",
            default="1",
        )
        if pick.strip().isdigit():
            idx = int(pick) - 1
            if 0 <= idx < len(show):
                chosen = show[idx]
            else:
                console.print("[red]Invalid number[/red]")
                return
        else:
            chosen = pick.strip()
        cfg["piper_voice"] = chosen
        save_config(cfg)
        clear_piper_voice_cache()
        console.print(f"  [green]Piper voice: {chosen}[/green]")
        return

    loc = Prompt.ask(
        "Locale",
        choices=["zh-TW", "zh-CN", "en-US", "ja-JP"],
        default="zh-TW",
    )
    ev = fetch_edge_voices(loc)
    if not ev:
        manual = Prompt.ask(
            "Could not list online. Enter Edge ShortName (e.g. zh-TW-HsiaoChenNeural)",
            default=cur_e,
        )
        cfg["edge_voice"] = manual.strip()
        save_config(cfg)
        console.print(f"  [green]Edge voice: {manual.strip()}[/green]")
        return

    max_show = 45
    show = ev[:max_show]
    for i, v in enumerate(show, 1):
        sn = v.get("ShortName", "")
        g = v.get("Gender", "")
        fn = (v.get("FriendlyName", "") or "")[:36]
        mark = "  <- current" if sn == cur_e else ""
        console.print(f"    {i:2}. {sn}  ({g}) {fn}{mark}")
    if len(ev) > max_show:
        console.print(f"    [dim]... {len(ev) - max_show} more in this locale[/dim]")
    pick = Prompt.ask(
        f"Number 1-{len(show)} or paste ShortName",
        default="1",
    )
    if pick.strip().isdigit():
        idx = int(pick) - 1
        if 0 <= idx < len(show):
            chosen = str(show[idx].get("ShortName", ""))
        else:
            console.print("[red]Invalid number[/red]")
            return
    else:
        chosen = pick.strip()
    cfg["edge_voice"] = chosen
    save_config(cfg)
    console.print(f"  [green]Edge voice: {chosen}[/green]")


def _handle_model(engine: ChatEngine):
    try:
        import ollama as ollama_client
        resp = ollama_client.list()
        models = _ollama_models_from_response(resp)
        if not models:
            console.print("[yellow]No models found.[/yellow]")
            return
        for i, m in enumerate(models, 1):
            mid = _ollama_model_id(m)
            marker = " [green]<- current[/green]" if mid == engine.model else ""
            console.print(f"  {i}. {mid}{marker}")
        choice = Prompt.ask("Pick model", default="1")
        try:
            idx = int(choice) - 1
            new_model = _ollama_model_id(models[idx])
        except (ValueError, IndexError):
            new_model = choice
        engine.model = new_model
        cfg = load_config()
        cfg["ollama_model"] = new_model
        save_config(cfg)
        console.print(f"  [green]Switched to {new_model}[/green]")
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")


def _handle_import():
    personal = get_personal_dir()
    console.print(f"  Scanning [cyan]{personal}[/cyan]...")
    results = scan_and_import(str(personal), callback=lambda f, s: console.print(f"    {f}: {s}"))
    imported = sum(1 for r in results if r["status"] == "imported")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    console.print(f"  [green]Done![/green] Imported: {imported}, Skipped: {skipped}")


def _handle_persona(engine: ChatEngine):
    from .onboarding import _list_personalities
    personas = _list_personalities()
    for i, p in enumerate(personas, 1):
        marker = " [green]<- current[/green]" if p["_file"] == load_config().get("personality") else ""
        console.print(f"  {i}. {p['name']} ({p['archetype']}){marker}")
    choice = Prompt.ask("Pick companion", default="1")
    try:
        idx = int(choice) - 1
        selected = personas[idx]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice[/red]")
        return
    cfg = load_config()
    cfg["personality"] = selected["_file"]
    save_config(cfg)
    engine.persona = engine._load_personality(selected["_file"])
    console.print(f"  [green]Switched to {selected['name']}[/green]")


def run():
    """Main entry point for the CLI."""
    console.print(LOGO)

    if is_first_run():
        cfg = run_onboarding()
    else:
        cfg = load_config()

    engine = ChatEngine(
        model=cfg.get("ollama_model"),
        personality=cfg.get("personality"),
    )
    
    console.print("\n[dim]Initializing memory palace...[/dim]")
    engine.start_session()

    user_name = cfg.get("user_name", "You")

    console.print()
    _print_startup_panel(engine)
    console.print(f"\n  [dim]Type your message, or /help for commands.[/dim]\n")

    while True:
        try:
            user_input = console.input(f"[bold green]{user_name}[/bold green] > ").strip()
        except (EOFError, KeyboardInterrupt):
            engine.shutdown()
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "/q"):
            engine.shutdown()
            console.print(f"  [magenta]{engine.get_companion_name()}[/magenta]: 下次見～\n")
            break
        elif cmd in ("/help", "/h"):
            console.print(HELP_TEXT)
            continue
        elif cmd == "/status":
            _handle_status(engine)
            continue
        elif cmd == "/voice":
            _handle_voice(engine)
            continue
        elif cmd in ("/tts",):
            _handle_tts()
            continue
        elif cmd in ("/voices", "/voicepick"):
            _handle_voices(engine)
            continue
        elif cmd == "/model":
            _handle_model(engine)
            continue
        elif cmd == "/import":
            _handle_import()
            continue
        elif cmd == "/persona":
            _handle_persona(engine)
            continue

        # --- Chat ---
        console.print(f"  [bold magenta]{engine.get_companion_name()}[/bold magenta]: ", end="")
        full_response = ""
        try:
            for chunk in engine.send_stream(user_input):
                console.print(chunk, end="", highlight=False)
                full_response += chunk
        except KeyboardInterrupt:
            console.print("\n  [dim](interrupted)[/dim]")
            continue

        console.print()

        cfg = load_config()
        if cfg.get("voice_enabled") and full_response.strip():
            tts_voice = cfg.get("edge_voice") or engine.persona.get(
                "tts_voice", "zh-TW-HsiaoChenNeural"
            )
            piper_v = cfg.get("piper_voice") or engine.persona.get("piper_voice")
            try:
                from .voice import speak
                speak(full_response, voice=tts_voice, piper_voice=piper_v)
            except Exception:
                pass

        _print_status_bar(engine)
        console.print()
