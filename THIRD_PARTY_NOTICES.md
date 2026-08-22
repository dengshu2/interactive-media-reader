# Third-party notices

Interactive Media Reader is MIT-licensed, but it installs or downloads the following third-party components at runtime. They are not redistributed in this repository and retain their own licenses.

| Component | Use | License |
| --- | --- | --- |
| [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Speech recognition model, converted to sherpa-onnx int8 format | CC BY 4.0 |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) and `sherpa-onnx-core` | Local ONNX inference runtime | Apache-2.0 |
| [NumPy](https://github.com/numpy/numpy) | Audio and timing arrays | BSD-3-Clause |

The generated reader contains only this project's static assets, generated transcript data, and a locally normalized audio-only AAC playback file. It does not contain or link source video, or bundle the ASR model or Python dependencies.
