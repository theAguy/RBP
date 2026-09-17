# Competitor registry

This registry prevents methods from being silently added or removed. “Core”
means part of the first full comparison; it does not mean the method's original
software must run unchanged.

| Method | Tier | Native task | Main issue | Current decision |
|---|---|---|---|---|
| DeepRiPe | Core 1 | Multitask binary binding | Legacy TensorFlow/Keras; original grouping and annotations | Modern implementation plus fidelity checks |
| Multi-resBind | Core 2 | Multi-label residual binary binding | Python 3.7-era stack; very close to the in-house idea | Inspect official code first; port only if necessary |
| PrismNet-seq | Core 3 | Per-protein binary binding | Original PyTorch 1.1; fixed 101-nt design | Use official sequence-only architecture; modern port if required |
| RNAProt | Optional 1 | Per-protein binary binding/profile | Separate Python 3.8 environment; optional features | Try official sequence-only environment after core pilot |
| DeepCLIP | Optional 2 | Per-protein binary binding/profile | Legacy dependencies and short native windows | Add only if core methods are insufficient |
| BERT-RBP | Optional 3 | Per-protein binary binding | Old DNABERT/CUDA stack and high GPU demand | Do not prioritize |
| GraphProt / GraphProt2 | Optional 4 | Per-protein sequence/structure binding | Structure and genomic-annotation pipeline | Coordinate-enabled secondary candidate |
| iDeepS | Logged | Per-protein sequence/structure binding | Legacy implementation; redundant for first comparison | No initial implementation |
| Pysster | Logged | Per-protein sequence/structure classification | Adds another single-task CNN | No initial implementation |
| MultiRBP | Logged | Multitask binding/affinity | Different original data/task | Revisit only if multitask coverage is challenged |
| RBPNet | Exploratory | Nucleotide-level crosslink counts | Requires target/control count tracks; not binary classification | Excluded from headline comparison |

## Implementation rule

For each core method, first time-box an official-code and published-benchmark
smoke test. Use isolated pinned environments or containers. If the original code
cannot be adapted cleanly, implement the architecture in the shared framework
and label it a modern reimplementation. Never imply that a retrained port is the
authors' released model.
