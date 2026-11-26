"""Integrations with training frameworks.

Each framework has its own submodule, imported only by the code that uses it,
so `import nuboard` never imports a framework:

- `nuboard.integrations.lightning`: `NuBoardLogger` for PyTorch Lightning.
- `nuboard.integrations.huggingface`: `NuBoardCallback` for the Hugging Face
  `Trainer`.

None of them adds a dependency: each uses the framework the script already has.
"""
