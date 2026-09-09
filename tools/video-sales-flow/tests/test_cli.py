from video_sales_flow.cli import build_parser


def test_generate_parser_accepts_multiple_outfits_and_explicit_google_flow_engine() -> None:
    args = build_parser().parse_args(
        [
            "generate",
            "--model",
            "model.jpg",
            "--outfit",
            "shirt.png",
            "--outfit",
            "jacket.png",
            "--count",
            "4",
            "--motion",
            "catwalk",
            "--motion",
            "pose",
            "--engine",
            "google-flow",
        ]
    )

    assert args.command == "generate"
    assert args.model == "model.jpg"
    assert args.outfits == ["shirt.png", "jacket.png"]
    assert args.count == 4
    assert args.motions == ["catwalk", "pose"]
    assert args.engine == "google-flow"


def test_generate_parser_defaults_motion_to_auto_at_execution_layer() -> None:
    args = build_parser().parse_args(
        ["generate", "--model", "model.jpg", "--outfit", "shirt.png"]
    )

    assert args.motions is None
    assert args.count == 3
    assert args.engine is None


def test_telegram_parser_accepts_google_flow_and_poll_timeout() -> None:
    args = build_parser().parse_args(
        ["telegram", "--engine", "google-flow", "--poll-timeout", "20"]
    )

    assert args.command == "telegram"
    assert args.engine == "google-flow"
    assert args.poll_timeout == 20
