# Lc0 analysis on Google Colab A100

[Open the notebook in Colab](https://colab.research.google.com/github/sennseics2-ux/liga/blob/main/notebooks/lc0-a100-analysis.ipynb)

1. In Colab, choose **Runtime → Change runtime type → GPU → A100** and connect.
2. Run notebook setup cells 1–4. They compile Lc0 v0.32.1 with the CUDA FP16 backend and download the official BT4-it332 network. Allow several minutes for the first build and network download.
3. On a Liga game review, pause replay on the exact position you want. Open the desktop browser console (F12 → Console), then paste the snippet below. It copies the displayed FEN and recorded move history.
4. Paste the copied JSON between the triple quotes in notebook cell 5. A full FEN alone is also supported. Keep the JSON when possible: Lc0 uses position history and repetition information.
5. Run cells 5–7. Confirm the displayed board and side to move. Begin with 120 seconds and 3 candidate moves; try 300–600 seconds or MultiPV 1 for a deeper single-line search.
6. Read the evaluation from White's perspective: positive favours White, negative favours Black. W/D/L percentages mean White win / draw / Black win. The line is a suggested continuation. Cell 8 optionally downloads the analysis JSON.

```javascript
(() => {
  const source = document.getElementById('replay-data');
  if (!source) throw new Error('Open a recorded game replay first.');
  if (document.querySelector('[data-action="play"]')?.getAttribute('aria-pressed') === 'true') {
    throw new Error('Pause the replay before exporting.');
  }
  const replay = JSON.parse(source.textContent);
  const buttons = [...document.querySelectorAll('[data-moves] button.replay-move')];
  const ply = buttons.findIndex(button => button.getAttribute('aria-current') === 'step') + 1;
  copy(JSON.stringify({
    fen: replay.positions[ply],
    initial_fen: replay.positions[0],
    moves: replay.moves.slice(0, ply).map(move => move.uci)
  }, null, 2));
})();
```

Changing the visual board orientation does not change the exported position. The JSON includes the move history available from the recorded PGN's starting position. Colab's output stays separate from the website.

The notebook's Python cells, position parsing and real website export were checked locally, including initial positions, several selected plies and flipped boards. An A100/CUDA runtime was not available for execution here; the actual build and GPU analysis run in your Colab session.

Sources: [Lc0 source/build instructions](https://github.com/LeelaChessZero/lc0/tree/v0.32.1) and [official recommended networks](https://lczero.org/play/networks/bestnets/).
