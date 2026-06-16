"""Entry point for the Kubernetes MCP server."""

from kubernetes_mcp import mcp


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
