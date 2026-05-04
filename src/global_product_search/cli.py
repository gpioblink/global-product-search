from __future__ import annotations

import json
import logging
from wsgiref.simple_server import make_server

import typer

from .api import create_app
from .engine import SearchEngine

app = typer.Typer(add_completion=False, help="Global product search CLI.")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    list_extractors: bool = typer.Option(
        False,
        "--list-extractors",
        help="List available extractors and exit.",
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging."),
) -> None:
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, format="%(message)s")
    engine = SearchEngine(debug=debug)
    ctx.obj = engine

    if list_extractors:
        for extractor in engine.list_extractor_infos():
            typer.secho(extractor.name, fg=typer.colors.CYAN, bold=True)
            typer.secho(
                f"  categories: {', '.join(extractor.genres) if extractor.genres else '-'}",
                fg=typer.colors.GREEN,
            )
            typer.secho(
                f"  flags: {', '.join(extractor.flags) if extractor.flags else '-'}",
                fg=typer.colors.MAGENTA,
            )
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def search(
    ctx: typer.Context,
    text: str,
    limit: int = typer.Option(10, "--limit", min=1, help="Maximum number of results."),
    json_output: bool = typer.Option(False, "--json", help="Emit results as JSON."),
    show_raw_payload: bool = typer.Option(
        False,
        "--show-raw-payload",
        help="Include raw upstream payloads in human-readable output.",
    ),
) -> None:
    engine = ctx.obj
    assert isinstance(engine, SearchEngine)
    try:
        results = engine.search_text(text, limit=limit)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(
            json.dumps(
                [candidate.model_dump() for candidate in results],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not results:
        typer.secho("No results found.", fg=typer.colors.YELLOW)
        return

    for index, candidate in enumerate(results, start=1):
        typer.secho(f"[{index}] {candidate.title}", fg=typer.colors.CYAN, bold=True)
        typer.secho(f"  source: {candidate.source}", fg=typer.colors.BLUE)
        typer.secho(
            f"  price: {candidate.price if candidate.price is not None else '-'}",
            fg=typer.colors.GREEN,
        )
        typer.secho(f"  shop: {candidate.shop_name or '-'}", fg=typer.colors.GREEN)
        typer.secho(f"  description: {candidate.description or '-'}", fg=typer.colors.WHITE)
        typer.secho(f"  image_url: {candidate.image_url or '-'}", fg=typer.colors.MAGENTA)
        typer.secho(f"  brand: {candidate.brand or '-'}", fg=typer.colors.MAGENTA)
        typer.secho(f"  model: {candidate.model or '-'}", fg=typer.colors.MAGENTA)
        typer.secho(
            f"  gtins: {', '.join(candidate.gtins) if candidate.gtins else '-'}",
            fg=typer.colors.MAGENTA,
        )
        typer.secho(f"  url: {candidate.url}", fg=typer.colors.BLUE)
        typer.secho(f"  score: {candidate.score:.1f}", fg=typer.colors.YELLOW)
        if show_raw_payload:
            typer.secho("  raw_payload:", fg=typer.colors.WHITE, bold=True)
            typer.echo(
                json.dumps(
                    candidate.raw_payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        typer.echo("")


@app.command()
def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", min=1, max=65535, help="Bind port."),
) -> None:
    engine = ctx.obj
    assert isinstance(engine, SearchEngine)

    typer.echo(f"Serving API on http://{host}:{port}")
    typer.echo("Routes: GET /extractors, GET /search?q=<query>&limit=10")
    api_app = create_app(engine=engine)
    with make_server(host, port, api_app) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            typer.echo("Stopping API server.")
