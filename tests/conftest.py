def pytest_addoption(parser):
    parser.addoption(
        "--robustness",
        action="store_true",
        help="also run the third-party spec checks (downloads ~17 MB)",
    )


def pytest_configure(config):
    if config.getoption("--robustness"):
        config.option.markexpr = ""
