"""PPT Studio CLI — pptctl command-line tool.

Usage:
    python -m cli.pptctl project create --name "测试项目" --canvas portrait_9_16
    python -m cli.pptctl project list
    python -m cli.pptctl source set --project abc123 --file article.md
    python -m cli.pptctl run start --project abc123 --stop-at image_review
    python -m cli.pptctl run status --project abc123
    python -m cli.pptctl run resume --project abc123
    python -m cli.pptctl artifacts list --project abc123 --type image
    python -m cli.pptctl diagnostics
"""
