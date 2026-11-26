# Local LLMs (Gemma 4 via Ollama) for Structured-Output Tasks + Fine-tune Go/No-Go

Research date: 2026-11-24. Hardware assumed: desktop RTX 4070 Super 12 GB + Ryzen 7 5800X + ~32 GB DDR4; laptop RTX 3060 Mobile 6 GB; Proxmox box with RX 6700 XT 12 GB (gfx1031), 16 GB RAM.
Research budget was limited to about 17 tool calls, so some numbers are inferred. Those are labelled in each "Inferences" section.

## Q1. What is Gemma 4, and what do the Ollama tags gemma4:12b / gemma4:26b / "nodraft" correspond to?

### Takeaway
Gemma 4 is Google's Apache-2.0 open model family. It launched on 2 April 2026 with E2B, E4B, 26B-A4B (MoE) and 31B (dense). A dense "12B Unified" was added on about 3 June 2026. `gemma4:26b` is the 26B-A4B MoE: 25.2B total parameters, 3.8B active, 128 experts with 8 active. `gemma4:12b` is the dense 11.95B Unified model. All sizes support native function calling, configurable thinking, a 256K context (128K on the edge models) and image input. The "draft"/MTP variants pair the model with a small Multi-Token-Prediction drafter for speculative decoding, so "nodraft" is almost certainly the same weights with no drafter attached.

### Cited Findings
- Released 2 April 2026 with four sizes (E2B, E4B, 26B MoE, 31B dense). Apache 2.0 license. Google says it has "native support for function-calling, structured JSON output, and native system instructions". Trained on 140+ languages. Context is 128K on the edge models and up to 256K on the larger ones. The 31B was #3 and the 26B #6 among open models on Arena AI at launch. — [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/)
- The 12B was a later, separate release: "Introducing Gemma 4 12B: a unified, encoder-free multimodal model". One third-party source gives the date as 3 June 2026. — [Google blog 12B](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/); [techsy.io](https://techsy.io/en/blog/gemma-4-12b); [Unsloth on X](https://x.com/UnslothAI/status/2062207258810053084)
- Model card architecture table:

  | Size | Type | Params | Layers | Context |
  |---|---|---|---|---|
  | E2B | Dense | 5.1B (2.3B effective) | 35 | 128K |
  | E4B | Dense | 8B (4.5B effective) | 42 | 128K |
  | 12B Unified | Dense | 11.95B | 48 | 256K |
  | 26B A4B | MoE | 25.2B total / 3.8B active | 30 | 256K |
  | 31B | Dense | 30.7B | 60 | 256K |

  The 12B Unified is "encoder-free": it projects image patches and audio directly into the embedding space. Audio is supported on E2B, E4B and 12B. Thinking is toggled with the `<|think|>` control token. The model was pretrained on 140+ languages, with "out-of-the-box support for 35+ languages". — [Gemma 4 model card](https://gemma.ai/models/gemma-4/model-card/) (ai.google.dev/gemma/docs/core/model_card_4 redirects here)
- The Ollama library lists 26b as MoE with 3.8B active of 25.2B and 8 of 128 experts active. Default q4 tags are 16–19 GB for 26b and 7.7–8.0 GB for 12b. Context is 256K. Input is text plus image. Native function calling. Thinking uses `<|think|>`. — [ollama.com/library/gemma4](https://ollama.com/library/gemma4)
- Ollama tag list: 51 tags, covering QAT, Q4_K_M, Q8_0, BF16 and MLX builds. It includes an MTP tag, `26b-a4b-it-mtp-q4_K_M`, and `31b-coding-mtp-bf16`. — [ollama.com/library/gemma4/tags](https://ollama.com/library/gemma4/tags)
- MTP: Gemma 4 ships a small autoregressive drafter that was trained alongside the target model. The drafter proposes several tokens and the target verifies them in a single pass, so output quality is unchanged. Ollama added a Modelfile `DRAFT` directive and an `ollama create --quantize-draft` flag. — [Ollama PR #15980](https://github.com/ollama/ollama/pull/15980); [pooyagolchian blog](https://pooyagolchian.com/blog/gemma-4-ollama-multi-token-prediction-local-2026/)
- The 12B MTP drafter ships as `mtp-gemma-4-12B-it.gguf` (Q4_0). The 26B drafter `mtp-gemma-4-26B-A4B-it.gguf` is about 460 MB. — [Unsloth 12B GGUF MTP README](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/blob/main/MTP/README.md); [carteakey.dev](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)
- Instruction-tuned benchmarks (model card):

  | Benchmark | 12B | 26B-A4B | 31B |
  |---|---|---|---|
  | MMLU-Pro | 77.2 | 82.6 | 85.2 |
  | GPQA Diamond | 78.8 | 82.3 | 84.3 |
  | LiveCodeBench v6 | 72.0 | 77.1 | 80.0 |
  | MMMLU (multilingual) | 83.4 | 86.3 | 88.4 |

  — [model card](https://gemma.ai/models/gemma-4/model-card/)
- I found no published Czech-specific score for Gemma 4, such as BenCzechMark. — [search summary; BenCzechMark paper](https://arxiv.org/pdf/2412.17933)

### Inferences
- "gemma4-26b-nodraft" looks like a user-created copy of the 26B without the `DRAFT` drafter attached. It may have been made because MTP and format/tools interact badly, or because the drafter costs VRAM. Run `ollama show gemma4-26b-nodraft --modelfile` to confirm.
- The 18 GB size of the pulled 26b matches the Q4_K_M MoE. That will not fit fully in 12 GB of VRAM.
- Czech quality is probably decent, since Czech is a mid-resource EU language and MMMLU is high. Still, verify it with a quick human read of 10 generated reviews, because no Czech benchmark exists.

### Gaps
- Whether Czech is in the "35+ out-of-the-box" list. I did not see the list.
- IFEval and BFCL/tau2 numbers for 12B vs 26B. They were not in the extracted model-card text, so check the technical report ([arXiv 2607.02770](https://arxiv.org/html/2607.02770v1)).
- Whether Ollama's CUDA (non-MLX) runner supports MTP drafting yet. As of late May 2026 the MLX runner shipped first and "other runners are being validated" ([pooyagolchian](https://pooyagolchian.com/blog/gemma-4-ollama-multi-token-prediction-local-2026/)). I found no confirmation for CUDA in Ollama. llama.cpp mainline does support it ([carteakey](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)).

## Q2. Ollama structured outputs (`format` JSON schema) and tool calling with Gemma 4: how they work and known issues

### Takeaway
`format` works on Gemma 4, but it has a history of interacting badly with thinking mode. With `think=false` the schema was silently ignored until Ollama 0.21.1, which fixed it for gemma4. In 0.35.1 there is an open bug: with `think=true`, if the model answers without reasoning, the output is not constrained. MLX builds ignore `format` entirely, so only use the GGUF models on Linux. Tool-call parsing for Gemma 4 in Ollama has been buggy all year, with malformed arguments, trailing garbage and reasoning loops. Treat tool calling as unreliable and validate everything.

### Cited Findings
- Issue #15260: `think=false` + `format` meant the constraint was silently ignored on gemma4/qwen3.5. Root cause: format masking was deferred until the end-of-thinking token. Affected 0.20.0 and 0.21.0. Fixed for gemma4 only in 0.21.1 (PR #15678). — [ollama#15260](https://github.com/ollama/ollama/issues/15260)
- Issue #18774 (open, Ollama 0.35.1): with `think:true` + JSON schema, gemma4:e4b answered directly without reasoning and the output was unconstrained (3 of 3 violations). The grammar expects a thinking block first. Workaround: `think:false`, which produced valid schema output. Fix PR #18783 is pending. — [ollama#18774](https://github.com/ollama/ollama/issues/18774)
- MLX runner: `format` is ignored (#16776, #17013, #17183 on gemma4:12b-mlx), or generation never terminates (#18567). GGUF builds honour the schema. — [#16776](https://github.com/ollama/ollama/issues/16776), [#17183](https://github.com/ollama/ollama/issues/17183), [#18567](https://github.com/ollama/ollama/issues/18567)
- Open issue #15540: "structured output not enforced on qwen 3.5 / gemma 4". — [#15540](https://github.com/ollama/ollama/issues/15540)
- Tool-calling parser bugs in Ollama gemma4:
  - 0.20.x parse errors ([#15315](https://github.com/ollama/ollama/issues/15315), [#15241](https://github.com/ollama/ollama/issues/15241))
  - system prompt + `think:false` + tools drops tool_calls ([#15539](https://github.com/ollama/ollama/issues/15539))
  - `call::`/BEGIN_ARG syntax followed by a `<|channel>thought` loop to the token cap ([#18275](https://github.com/ollama/ollama/issues/18275))
  - trailing garbage after the closing brace ([#18649](https://github.com/ollama/ollama/issues/18649))
  - keys with spaces ([#18390](https://github.com/ollama/ollama/issues/18390))
  - `key=value` args ([#17882](https://github.com/ollama/ollama/issues/17882))
- A Hugging Face forum thread reports that Gemma 4 malforms tool calls under load (long context + reasoning) and then loops, across vLLM, llama.cpp, Ollama and oobabooga. — [HF forum](https://discuss.huggingface.co/t/gemma-4-bug-fixes-and-research-request/176979)

### Inferences
- Recommended config for task (a), spec extraction: GGUF gemma4 on a recent Ollama (0.35.x), `think:false`, `format=<JSON schema>`, `temperature` around 0–0.3, then a Pydantic/jsonschema validator plus a retry loop. Ollama's constraint comes from llama.cpp-style grammar sampling. It enforces structure, types and enums, but not semantic rules such as numbers matching. Keep the schema reasonably flat. Avoid `anyOf`/`oneOf` and `$ref` recursion where possible, and put long free-text fields last.
- If thinking helps quality, use two passes. Pass 1 reasons with thinking on and free text. Pass 2 runs with `think:false` and `format=schema` to emit the JSON. This avoids #18774 entirely.
- For task (c), the detective agent, do not depend on native tool calling through Ollama. Run a manual "ReAct via JSON" loop instead: each turn the model emits a `format`-constrained JSON `{action, args}` or `{final: {narrative, events[]}}`, and your code dispatches the tools. That swaps a fragile parser for a grammar that is enforced.
- Pin and record the Ollama version before the hackathon. Regressions are frequent.

### Gaps
- The exact grammar features supported (`pattern`, `minItems`, `$ref`) in the current Ollama schema-to-grammar converter. I did not verify this against source.
- No hard data on JSON validity rates of gemma4:12b vs 26b under `format`.

## Q3. Realistic speed on the RTX 4070 Super 12 GB, and context/KV-cache settings

### Takeaway
The 12B Q4 (~7–8 GB) fits fully in 12 GB with room for a 16–32K context. Expect roughly 45–65 tok/s, which is an inference from bandwidth, not a measurement. The 26B-A4B Q4 (~16–19 GB) must partially offload. Because it is MoE with only 3.8B active, it runs at about 32–38 tok/s with partial offload on a 4070-class card. Hand-tuned llama.cpp with QAT reaches about 69 tok/s, and about 100 tok/s with MTP. So the 26B is usable on this hardware. A 2–3k-token JSON output from it takes about 1 minute in Ollama, or 20–40 s with tuned llama.cpp.

### Cited Findings
- RTX 4070 12 GB + i5-12600K + 32 GB DDR5-6000, llama.cpp mainline, Gemma 4 26B-A4B:
  - Baseline: 38.5 tok/s
  - QAT UD-Q4_K_XL: 69.0 tok/s
  - QAT + MTP drafter (~460 MB, `--spec-draft-n-max 2`): 100.6 tok/s at a 131K context
  - Flags: `--flash-attn on --fit on --fit-target 1536 -ctk f16 -ctv f16 -t 10`
  - Quantised KV cache "degrades the MTP acceptance rate to near zero on Gemma 4", so use f16 KV with MTP.
  — [carteakey.dev](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)
- Gemma 4 26B-A4B on an RTX 4070 with partial offload runs at about 32 tok/s. Q4_K_M needs about 16 GB against about 10.8 GB usable. — [modelfit.io](https://modelfit.io/can-i-run/gemma4-26b-a4b-q4-on-rtx-4070/); [willitrunai](https://willitrunai.com/models/gemma-4-26b-a4b) (~170 tok/s fully on a 4090)
- Gemma 4 12B needs about 6.6 GB at Q4_K_M and fits on 8 GB GPUs. Unsloth says it runs "on just 8GB RAM via Dynamic GGUFs". — [techsy.io](https://techsy.io/en/blog/gemma-4-12b); [Unsloth X](https://x.com/UnslothAI/status/2062207258810053084)
- MTP on 12B in llama.cpp: 75.3 → 178.7 tok/s (+137%, GPU unspecified). On a B200: 52 → 162 tok/s with 0.70 acceptance. — [XDA](https://www.xda-developers.com/most-people-running-gemma-4-locally-havent-switched-on-the-free-speedup-google-shipped-for-it/); [Unsloth MTP README](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/blob/main/MTP/README.md)

### Inferences
- The 4070 Super has ~504 GB/s bandwidth. A ~7.5 GB 12B Q4 therefore has a theoretical ceiling of ~65 tok/s, so 45–60 tok/s is realistic in Ollama. A 3k-token spec takes ~50–70 s on 12B and ~80–100 s on 26B in Ollama.
- The Ryzen 5800X + DDR4 is slower than DDR5-6000 for offloaded experts, so expect 26B in Ollama at the low end, about 25–35 tok/s.
- The laptop RTX 3060 6 GB can only run the 12B with partial offload (slow, ~10–20 tok/s estimated) or E4B. Use it as a client or for E4B.
- Ollama settings:
  - `OLLAMA_FLASH_ATTENTION=1`
  - `num_ctx` 8192–16384 per request. The default can be small, and too-small silently truncates long prompts plus schema.
  - `OLLAMA_KV_CACHE_TYPE=q8_0` halves KV memory and is fine without MTP. Avoid it if you use MTP drafting.
  - `OLLAMA_NUM_PARALLEL=1` on 12 GB, to avoid duplicate KV.
  - `keep_alive=-1` to avoid reloads.

### Gaps
- No direct measurement of gemma4:12b tok/s on a 4070 Super in Ollama.
- No 5800X/DDR4-specific 26B numbers.

## Q4. Is 26B worth it over 12B for spec extraction, and are there better local alternatives or runtimes?

### Takeaway
26B-A4B is consistently 3–5 points better than 12B on knowledge and reasoning benchmarks, and +2.9 on MMMLU (multilingual). On this box it costs about 1.5–2x the latency and leaves almost no VRAM headroom. For schema-constrained extraction, structure comes from the grammar and the validator, so the gap mainly shows up in semantic accuracy and Czech fluency. Plan: use 12B as the default for the iteration loop and bulk generation. Use 26B for the final or "hard" extraction runs and for the detective narrative, if latency allows. I found no JSON-mode or BFCL head-to-head data.

### Cited Findings
- 12B vs 26B: MMLU-Pro 77.2 vs 82.6, GPQA 78.8 vs 82.3, LiveCodeBench 72.0 vs 77.1, MMMLU 83.4 vs 86.3. — [model card](https://gemma.ai/models/gemma-4/model-card/)
- Comparison write-ups say Gemma 4 is "clean and consistent with structured outputs", while Qwen 3.5 is "more aggressive about calling tools" and its thinking produces more structured plans. These are opinion pieces, not benchmarks. — [MindStudio](https://www.mindstudio.ai/blog/gemma-4-vs-qwen-3-5-open-weight-comparison)
- Ollama's `think=false`+`format` fix was scoped to gemma4 only, and qwen3.5/3.6 remained affected at the time of the issue. — [ollama#15260](https://github.com/ollama/ollama/issues/15260)
- llama.cpp ROCm vs Vulkan and MTP support exist in llama.cpp mainline. Hand-tuned llama.cpp beat Ollama-style defaults by 2.6x on the 26B (38.5 → 100.6 tok/s). — [carteakey.dev](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)

### Inferences
- Alternatives:
  - Qwen3.5/3.6 (e.g. a 30B-A3B-class MoE) is a reasonable A/B candidate for the tool-calling agent, but on Ollama it carries the unfixed think+format bug, so run it with thinking disabled or through llama-server.
  - Mistral Small 3.x (24B dense) would need heavy offload on 12 GB and be slower than the 26B-A4B MoE.
  - Given the time box, stick to Gemma 4 and keep one Qwen model as a fallback.
- Runtime: `llama-server` (llama.cpp) with `--json-schema`/`response_format` gives the same GBNF constraint as Ollama, plus `--n-cpu-moe`/`--fit` and MTP drafting on CUDA. That roughly doubles the 26B's speed. vLLM with xgrammar needs the whole model in VRAM, which is impractical for the 26B on 12 GB. Outlines/xgrammar add little over GBNF for these schemas.

### Gaps
- No public IFEval, BFCL or JSONSchemaBench comparison of gemma4 12B vs 26B vs Qwen3.x.

## Q5. Is running on the RX 6700 XT (gfx1031) via ROCm or Vulkan feasible?

### Takeaway
Yes, it works. Use Ollama with ROCm and `HSA_OVERRIDE_GFX_VERSION=10.3.0`, or llama.cpp with Vulkan, which needs no override. Decode speed is in the same league as an older NVIDIA card. The Proxmox host has only 16 GB of system RAM, so run 12B fully on the GPU there. The 26B cannot offload well on that host.

### Cited Findings
- The RX 6700 XT is gfx1031, which ROCm libraries don't ship. `HSA_OVERRIDE_GFX_VERSION=10.3.0` (treat it as gfx1030) makes Ollama and llama.cpp work. For Ollama, add `Environment="HSA_OVERRIDE_GFX_VERSION=10.3.0"` to the systemd unit. Vulkan needs no override. — [selfhost.directory](https://selfhost.directory/models/amd); [localaimaster](https://localaimaster.com/blog/rocm-unsupported-gpu-hsa-override)
- llama.cpp gfx1031 report (model unspecified in the summary): ROCm gave 653.9 t/s prefill and 34.6 t/s decode; Vulkan gave 354.4 t/s prefill and 40.9 t/s decode. — [llama.cpp#26702](https://github.com/ggml-org/llama.cpp/issues/26702)

### Inferences
- Under Proxmox you also need GPU passthrough to a VM, or an LXC with /dev/kfd and /dev/dri. Use this box as a second inference worker, for example for bulk Czech review generation with 12B, in parallel with the desktop.

### Gaps
- Gemma 4-specific tok/s on gfx1031 was not found.

## Q6. Fine-tuning: Unsloth support, VRAM needs, effort, and go/no-go for a 24h hackathon. Also, sampling settings.

### Takeaway
Unsloth supports all Gemma 4 sizes and exports GGUF for Ollama. QLoRA on 12B should fit in 12 GB with batch size 1 and gradient checkpointing (an inference; no official 12B number was found). The 26B-A4B MoE needs more than 40 GB for LoRA, and Unsloth advises against 4-bit QLoRA on it, so it is not trainable at home.

**Recommendation: NO-GO for fine-tuning during the 24h event.**
- Use schema-constrained decoding, a few in-schema examples, and a validator-retry loop.
- Only consider a pre-event LoRA on 12B if prep is allowed and you already have more than 500 high-quality gold pairs.

Sampling settings:
- Google's default is temperature 1.0, top_p 0.95, top_k 64. Keep that for the creative Czech text.
- For extraction, lower it (temperature 0–0.3). This is my recommendation, not Google's.

### Cited Findings
- Unsloth Gemma 4 VRAM needs:
  - E2B: 8 GB for LoRA
  - E4B: 17 GB for LoRA
  - 26B-A4B: more than 40 GB for LoRA. For the MoE, use 16-bit LoRA rather than 4-bit QLoRA.
  - 31B: 22 GB QLoRA
  - Use chat template `gemma-4` or `gemma-4-thinking`.
  - Exports GGUF (q4_k_m, q8_0, f16) for Ollama.
  - It lists fixed bugs (gradient-accumulation loss inflation, KV-cache issues).
  — [Unsloth Gemma 4 training guide](https://unsloth.ai/docs/models/gemma-4/train); [secondary summary](https://gemma4.dev/guides/gemma-4-unsloth-qlora)
- Unsloth supports training 12B via Unsloth Studio and 4-bit/16-bit LoRA through bitsandbytes. It recommends `use_gradient_checkpointing="unsloth"`, batch size 1, and reducing max_seq_length on OOM. — [Unsloth X](https://x.com/UnslothAI/status/2062207258810053084); [gemma.ai Unsloth page](https://gemma.ai/deployment/unsloth/)
- Google-recommended sampling: `temperature=1.0, top_p=0.95, top_k=64`. — [model card](https://gemma.ai/models/gemma-4/model-card/); [ollama library](https://ollama.com/library/gemma4)

### Inferences
- 12B QLoRA VRAM: 4-bit weights are ~7 GB, plus LoRA, optimizer and activations. That fits in 12 GB at seq_len ~4k with batch size 1. But task (a) needs input plus 1–3k output tokens, so sequences of ~4–6k are tight. Expect roughly 1–3 h for 1,000 examples × 1 epoch on a 4070 Super. This is a rough estimate.
- Then add GGUF export, quantization, an Ollama Modelfile with the correct template, and an evaluation run. Realistically that is half a day including debugging, plus the risk of chat-template or thinking-token mismatches.
- Expected gain is small over schema-constrained decoding plus 2–3 in-schema examples plus a validator-retry loop. The grammar already guarantees syntax. A fine-tune mostly improves field-filling conventions, which a good system prompt and examples also handle. For Czech review generation, a fine-tune risks overfitting style for little benefit.
- Go only if all of the following hold: pre-hackathon prep is allowed; you have more than 500 gold (description → spec) pairs from the organisers' format; the 12B baseline still fails validation more than 10–15% of the time after retries.
- Model-per-task plan:
  - **(a) Spec extraction:** gemma4:12b (GGUF) with `think:false`, `format=schema`, temperature 0.1, `num_ctx` 16384, validator + up to 2 retries feeding the error back. Rerun failures on gemma4:26b. Optionally do a two-pass "think, then format".
  - **(b) Czech reviews/tickets:** gemma4:12b with temperature ~0.9–1.0, top_p 0.95, top_k 64. Have code compute the numbers deterministically and pass them in. Use a `format` schema `{text, rating, ...}` and post-check the numbers. Scale out across the desktop and the RX 6700 XT box.
  - **(c) Detective agent:** gemma4:26b (or 12b for speed) with a manual JSON-action loop instead of native tools, `think:true` only in a separate reasoning pass, and a final `format`-constrained `{narrative, events[]}`.
  - Pin the Ollama version. Avoid MLX tags. Check whether "nodraft" is the safer choice with `format`.

### Gaps
- No official Unsloth VRAM figure for Gemma 4 12B QLoRA, and no measured training time on a 4070-class GPU.
- No published study quantifying fine-tune vs constrained-decoding gains for Gemma 4 extraction specifically.
