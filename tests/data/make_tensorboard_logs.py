"""Regenerate tests/data/tensorboard with the real writers (not needed to run tests).

Needs tensorflow-cpu, tensorboard, torch, tensorboardX and soundfile:

    python tests/data/make_tensorboard_logs.py tests/data/tensorboard tf
    python tests/data/make_tensorboard_logs.py tests/data/tensorboard torch
    python tests/data/make_tensorboard_logs.py tests/data/tensorboard tbx
"""

import sys

import numpy as np

out, which = sys.argv[1], sys.argv[2]
img = (np.random.rand(3, 16, 24) * 255).astype(np.uint8)
wav = np.sin(np.linspace(0, 44 * 2 * np.pi, 800)).astype(np.float32) * 0.5

if which == "tf":
    import tensorflow as tf
    from tensorboard.plugins.hparams import api as hp

    for name in ["train", "validation"]:
        w = tf.summary.create_file_writer(f"{out}/tf2/lr0.01/{name}")

        with w.as_default():
            for s in range(5):
                tf.summary.scalar("loss", 1.0 / (s + 1), step=s)
                tf.summary.scalar("acc", tf.constant(s, tf.int64), step=s)

            images = np.random.rand(2, 16, 24, 3).astype(np.float32)
            tf.summary.image("samples", images, step=4, max_outputs=2)
            tf.summary.audio("tone", wav.reshape(1, -1, 1), 8000, step=4)
            tf.summary.text("note", "hello **tf**", step=2)
            tf.summary.histogram("weights", np.random.randn(100), step=3)

        w.close()

    w = tf.summary.create_file_writer(f"{out}/tf2/lr0.01/train")

    with w.as_default():
        hp.hparams({"lr": 0.01, "optimizer": "adam", "layers": 3, "dropout_on": True})

    w.close()
elif which == "torch":
    from torch.utils.tensorboard import SummaryWriter

    w = SummaryWriter(f"{out}/torch/run_a")

    for s in range(5):
        w.add_scalar("train/loss", 2.0 / (s + 1), s)
        w.add_scalars("cmp", {"a": s, "b": -s}, s)

    w.add_image("img", img, 3)
    w.add_audio("snd", wav, 3, sample_rate=8000)
    w.add_text("txt", "torch text", 1)
    w.add_histogram("h", np.random.randn(50), 1)
    w.add_hparams({"lr": 0.1, "bs": 32, "opt": "sgd"}, {"hparam/acc": 0.9})
    w.close()
else:
    from tensorboardX import SummaryWriter

    w = SummaryWriter(f"{out}/tbx/exp1")

    for s in range(5):
        w.add_scalar("loss", 3.0 / (s + 1), s)

    w.add_image("img", img, 2)
    w.add_audio("snd", wav, 2, sample_rate=8000)
    w.add_text("txt", "tbx text", 1)
    w.close()
