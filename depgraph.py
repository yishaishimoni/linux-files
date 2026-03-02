"""
A tool that, like `pyreverse -o png` creates diagrams for Python Projects.
See: [pyreverse](https://pylint.readthedocs.io/en/latest/additional_tools/pyreverse/index.html)
Uses `ruff analyze` to retrieve the dependency graph
Adds the following features:
    + `--cluster`: Dependency hierarchy / grouping, for a more understandable layout
    + `--filter-disconnected`: Filtering disconnected nodes, to clean up __init__s and other boilerplate
    + `--ignore-init`: Filtering out `__init__` files, to clean up boilerplate
    + `--vertical`: Vertical layout (top-to-bottom) instead of horizontal (left-to-right)
    + `--format`: Output format (default: png)
    + `--output`: Output file name (default: packages)

Based on https://gist.github.com/rgon/115595265b1d5566f5734eb04bf97736

Usage:
    ruff analyze graph --no-type-checking-imports | python3 depgraph.py -c -fd -ii && xdg-open packages.svg
"""

import argparse
import json
import sys

from graphviz import Digraph


def create_dependency_graph(
    json_data: str,
    *,
    clustering: bool = False,
    filter_disconnected: bool = False,
    ignore_init: bool = False,
    vertical: bool = False,
):
    """
    Converts a JSON dependency graph into a Graphviz Digraph object,
    with optional clustering by package and submodule hierarchy.
    """
    data = _parse_json_data(json_data)
    if data is None:
        return None

    if ignore_init:
        data = _filter_init_files(data)

    dot = Digraph(comment="Python Dependency Graph", strict=True)
    dot.attr(rankdir="TB" if vertical else "LR")
    dot.attr("node", shape="box")

    all_nodes = _collect_all_nodes(data)

    if filter_disconnected:
        all_nodes = _filter_connected_nodes(data, all_nodes)

    if clustering:
        _add_clusters(dot, all_nodes)
    else:
        for node in all_nodes:
            dot.node(node, node)

    _add_edges(dot, data)

    return dot


def main():
    """
    Main entry point for the dependency graph generator.
    Reads JSON from stdin, creates a graph, and saves it to a file.

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    parser = _create_argument_parser()
    args = parser.parse_args()

    # Early return: check if stdin is available
    if sys.stdin.isatty():
        return _report_no_input_error(parser)

    # Read and validate input
    json_input, exit_code = _read_and_validate_stdin()
    if json_input is None:
        return exit_code

    # Create the dependency graph
    graph = create_dependency_graph(
        json_input,
        clustering=args.cluster,
        filter_disconnected=args.filter_disconnected,
        ignore_init=args.ignore_init,
        vertical=args.vertical,
    )

    if graph is None:
        print("Error: Failed to create dependency graph.", file=sys.stderr)
        return 1

    # Render the graph to file
    return _render_graph(graph, args.output, args.format)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_json_data(json_data: str):
    """Parse JSON data and handle errors."""
    try:
        return json.loads(json_data)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return None


def _filter_init_files(data: dict) -> dict:
    """Filter out __init__ files from sources and targets."""
    return {
        source: [t for t in targets if "__init__" not in t]
        for source, targets in data.items()
        if "__init__" not in source
    }


def _collect_all_nodes(data: dict) -> set:
    """Collect all nodes from data keys and values."""
    all_nodes = set(data.keys())
    for dependencies in data.values():
        all_nodes.update(dependencies)
    return all_nodes


def _filter_connected_nodes(data: dict, all_nodes: set) -> set:
    """Filter to keep only connected nodes."""
    incoming = {d for deps in data.values() for d in deps}
    outgoing = {src for src, deps in data.items() if deps}
    connected_nodes = incoming | outgoing
    return connected_nodes if connected_nodes else all_nodes


def _group_nodes_by_package(nodes: set) -> dict:
    """Group nodes by their top-level package."""
    packages = {}
    for node in nodes:
        top_level = node.split("/")[0]
        packages.setdefault(top_level, []).append(node)
    return packages


def _add_clusters(dot: Digraph, nodes: set):
    """Add clustered nodes to the graph."""
    packages = _group_nodes_by_package(nodes)

    for package, package_nodes in packages.items():
        if len(package_nodes) > 1:
            sg_gen = dot.subgraph(name=f"cluster_{package}")
            if not sg_gen:
                continue

            with sg_gen as package_cluster:
                package_cluster.attr(label=package, style="filled", color="#F0F0F0")
                for node in package_nodes:
                    sub_parts = node.split("/")[1:]
                    _create_subgraph_from_path(package_cluster, sub_parts, node)
        else:
            for node in package_nodes:
                dot.node(node, node)


def _add_edges(dot: Digraph, data: dict):
    """Add edges to the graph."""
    for source, targets in data.items():
        for target in targets:
            dot.edge(source, target)


def _create_subgraph_from_path(graph: Digraph, path_parts: list[str], full_path: str):
    """Recursively creates or adds to a nested subgraph hierarchy."""
    if not path_parts:
        # Base case: add the node itself
        graph.node(full_path, full_path)
        return

    sg_gen = graph.subgraph(name=f"cluster_{path_parts[0]}")
    if not sg_gen:
        return

    with sg_gen as c:
        c.attr(label=path_parts[0], style="filled", color="#DADADA")
        if len(path_parts) > 1:
            # Recursive step: handle the rest of the path
            _create_subgraph_from_path(c, path_parts[1:], full_path)
        else:
            # Reached a leaf node (file)
            c.node(full_path, full_path)


def _create_argument_parser() -> argparse.ArgumentParser:
    """
    Create and configure the argument parser for the dependency graph generator.

    Returns:
        argparse.ArgumentParser: Configured argument parser
    """
    parser = argparse.ArgumentParser(
        description="Generate a dependency graph from JSON data.",
        epilog="""
Examples:
  ruff analyze graph | python3 ./depgraph.py --cluster --filter-disconnected
  ruff analyze graph | python3 ./depgraph.py -c -fd -ii -o png
  ruff analyze graph | python3 ./depgraph.py --cluster && xdg-open packages.svg
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cluster",
        "-c",
        action="store_true",
        help="Enable clustering by package hierarchy.",
    )
    parser.add_argument(
        "--filter-disconnected",
        "-fd",
        action="store_true",
        help="Filter out disconnected/non-imported nodes.",
    )
    parser.add_argument(
        "--ignore-init",
        "-ii",
        action="store_true",
        help="Ignore __init__ files in the dependency graph.",
    )
    parser.add_argument(
        "--format",
        "-o",
        default="svg",
        choices=["svg", "png", "pdf"],
        help="Output format for the graph (default: svg).",
    )
    parser.add_argument(
        "--output",
        "-f",
        default="packages",
        help="Output filename without extension (default: packages).",
    )
    parser.add_argument(
        "--vertical",
        "-v",
        action="store_true",
        help="Use vertical layout (top-to-bottom) instead of horizontal (left-to-right).",
    )
    return parser


def _read_and_validate_stdin() -> tuple[str | None, int]:
    """
    Read and validate JSON input from stdin.

    Returns:
        tuple: (json_input, exit_code) where json_input is None on error
    """
    json_input = sys.stdin.read()
    if not json_input.strip():
        print("Error: Empty input received from stdin.", file=sys.stderr)
        return None, 1
    return json_input, 0


def _render_graph(graph: Digraph, output_name: str, format: str) -> int:
    """
    Render the graph to a file.

    Args:
        graph: The Graphviz Digraph object to render
        output_name: Output filename without extension
        format: Output format (svg, png, pdf)

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    try:
        # Note: graph.render() automatically appends the format extension
        graph.render(output_name, view=False, format=format, cleanup=True)
        output_file = f"{output_name}.{format}"
        print(f"Successfully created '{output_file}'")
        return 0
    except Exception as e:
        print(f"Error rendering graph: {e}", file=sys.stderr)
        return 1


def _report_no_input_error(parser: argparse.ArgumentParser) -> int:
    """
    Report error when no stdin input is provided.

    Args:
        parser: The argument parser to print help from

    Returns:
        int: Exit code (1 for error)
    """
    print("Error: No input data provided.", file=sys.stderr)
    print("Please pipe JSON data to the script's stdin.", file=sys.stderr)
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
