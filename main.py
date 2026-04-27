"""
Point d'entrée CLI — PropPilot.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s — %(message)s")


def print_banner():
    console.print(Panel(
        Text("🏠  PropPilot\nSystème agentique pour professionnels de l'immobilier français\n"
             "Propulsé par Claude Sonnet + LangGraph", justify="center"),
        style="bold blue",
    ))


@click.group()
def cli():
    """PropPilot — CLI de gestion et simulation."""
    pass


@cli.command()
def init():
    """Initialise la base de données."""
    print_banner()
    console.print("[bold]Initialisation...[/bold]")

    from memory.database import init_database
    init_database()

    from config.settings import get_settings
    s = get_settings()

    console.print(f"[green]✅ Base de données initialisée : {s.database_path}[/green]")

    # Affichage config
    table = Table(title="Configuration active", show_header=True)
    table.add_column("Paramètre", style="cyan")
    table.add_column("Valeur")

    table.add_row("Agence", s.agency_name)
    table.add_row("Tier", s.agency_tier)
    table.add_row("Claude disponible", "✅" if s.anthropic_available else "⚠️ Mode mock")
    table.add_row("Twilio disponible", "✅" if s.twilio_available else "⚠️ Mode mock")
    table.add_row("Base de données", s.database_path)

    console.print(table)
    console.print("\n[green]Prochaine étape :[/green] python scripts/seed_demo_data.py")


@cli.command()
def status():
    """Affiche le statut du système."""
    from config.settings import get_settings
    from memory.database import init_database
    from memory.lead_repository import get_pipeline_stats
    from memory.usage_tracker import get_usage_summary

    init_database()
    s = get_settings()

    print_banner()

    # Pipeline stats
    stats = get_pipeline_stats(s.agency_client_id)

    pipeline_table = Table(title=f"Pipeline — {s.agency_name}", show_header=True)
    pipeline_table.add_column("Statut", style="cyan")
    pipeline_table.add_column("Nb Leads", justify="right")

    status_labels = {
        "entrant": "📥 Entrants",
        "en_qualification": "🔄 En qualification",
        "qualifie": "⭐ Qualifiés",
        "rdv_booke": "📅 RDV bookés",
        "nurturing": "💌 Nurturing",
        "mandat": "📋 Mandats",
        "vendu": "🎉 Vendus",
        "perdu": "❌ Perdus",
    }

    for key, label in status_labels.items():
        pipeline_table.add_row(label, str(stats.get(key, 0)))

    console.print(pipeline_table)

    # Usage
    usage = get_usage_summary(s.agency_client_id, s.agency_tier)

    usage_table = Table(title=f"Usage — Forfait {s.agency_tier}", show_header=True)
    usage_table.add_column("Ressource", style="cyan")
    usage_table.add_column("Utilisé", justify="right")
    usage_table.add_column("Limite", justify="right")
    usage_table.add_column("Progression", justify="right")

    for key, data in usage.items():
        if not isinstance(data, dict):
            continue
        pct = data["pct"]
        limit = str(data["limit"]) if data["limit"] else "∞"
        bar_char = "█" if pct >= 90 else "▓" if pct >= 70 else "░"
        bar = bar_char * int(pct / 10) + "·" * (10 - int(pct / 10))
        color = "red" if pct >= 90 else "yellow" if pct >= 70 else "green"
        usage_table.add_row(
            data["label"],
            str(data["used"]),
            limit,
            f"[{color}]{bar} {pct:.0f}%[/{color}]",
        )

    console.print(usage_table)


@cli.command("simulate-lead")
@click.option("--type", "lead_type", default="acheteur", type=click.Choice(["acheteur", "vendeur", "locataire"]))
@click.option("--score", default=7, type=int, help="Score cible 1-10")
@click.option("--phone", default="+33699000001")
def simulate_lead(lead_type: str, score: int, phone: str):
    """Simule un flux lead complet end-to-end."""
    from config.settings import get_settings
    from memory.database import init_database
    from lib.sms_storage import store_incoming_sms

    init_database()
    s = get_settings()

    print_banner()
    console.print(f"[bold]Simulation lead {lead_type}...[/bold]")

    messages_by_type = {
        "acheteur": "Bonjour, je cherche à acheter un appartement 3 pièces à Lyon, budget 380 000€",
        "vendeur": "Bonjour, je veux vendre mon appartement à Paris 15e, 85m², belle copropriété",
        "locataire": "Bonjour, je recherche un T3 à Bordeaux pour 900€/mois maximum",
    }

    message = messages_by_type.get(lead_type, "Bonjour, j'ai un projet immobilier")

    console.print(f"\n[cyan]Message entrant :[/cyan] {message}")
    console.print(f"[cyan]Téléphone :[/cyan] {phone}\n")

    with console.status("Stockage en cours..."):
        result = store_incoming_sms(
            from_number=phone,
            to_number="",
            body=message,
            client_id=s.agency_client_id,
        )

    # Résultats
    results_table = Table(title="Résultats", show_header=False)
    results_table.add_column("Clé", style="cyan")
    results_table.add_column("Valeur")

    results_table.add_row("Lead ID", result.get("lead_id", "—")[:8] if result.get("lead_id") else "—")
    results_table.add_row("Nouveau lead", "oui" if result.get("is_new_lead") else "non")
    results_table.add_row("Stocké", "oui" if result.get("stored") else "non")

    console.print(results_table)

    console.print(f"\n[green]✅ Simulation terminée[/green]")


@cli.command("process-nurturing")
def process_nurturing():
    """Traite tous les follow-ups de nurturing dus."""
    from config.settings import get_settings
    from memory.database import init_database
    from agents.nurturing import NurturingAgent

    init_database()
    s = get_settings()

    console.print("[bold]Traitement des follow-ups nurturing...[/bold]")

    agent = NurturingAgent(client_id=s.agency_client_id, tier=s.agency_tier)
    results = agent.process_due_followups()

    if not results:
        console.print("[yellow]Aucun follow-up dû pour le moment.[/yellow]")
    else:
        table = Table(title="Follow-ups traités", show_header=True)
        table.add_column("Lead ID")
        table.add_column("Envoyé")
        table.add_column("Canal")
        table.add_column("Prochain")

        for r in results:
            table.add_row(
                r.get("lead_id", "—")[:8],
                "✅" if r.get("sent") else "❌",
                r.get("canal", "—"),
                r.get("next_followup", "—")[:10] if r.get("next_followup") else "Fin séquence",
            )

        console.print(table)

    console.print(f"\n[green]✅ {len(results)} follow-up(s) traité(s)[/green]")


@cli.command("dashboard")
def launch_dashboard():
    """Lance le dashboard Streamlit."""
    import subprocess
    console.print("[bold]Lancement du dashboard...[/bold]")
    subprocess.run(["streamlit", "run", str(ROOT / "dashboard" / "app.py")], check=True)


if __name__ == "__main__":
    cli()
