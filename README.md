# MTG Craft

> Gerador de folhas de impressão para cartas de Magic: The Gathering — A4, 3×3, corte perfeito.

Busca imagens em alta resolução diretamente do Scryfall (PNG 745×1040px), gera PDFs prontos para impressão com marcas de corte exatas no padrão CardTrader, e trata cartas de frente e verso (DFCs) em páginas duplex separadas.

---

## ✦ Funcionalidades

| Recurso | Descrição |
| --- | --- |
| **Busca Scryfall** | Autocomplete por nome, resultado sempre em inglês |
| **Importar lista** | Cola texto no formato Moxfield/Scryfall Export (`4 Lightning Bolt (M10) 146`) |
| **Import por URL** | Cole uma URL do **Moxfield** ou **Archidekt** e importe o deck inteiro |
| **Upload local** | Arraste JPG/PNG/WEBP diretamente para o app |
| **URL de imagem** | Imagem de qualquer URL pública — MTGBuilder, proxies, custom art |
| **Decks salvos** | Salve e carregue decks no navegador (localStorage) |
| **Preview A4** | Visualize as folhas em tempo real, com proporções exatas do PDF |
| **DFC duplex** | PDF separado com frentes e versos em colunas espelhadas (flip long-edge) |
| **Alta qualidade** | PNG 745×1040px do Scryfall em todas as cartas |
| **Mobile** | Interface responsiva — funciona em celular |

---

## Layout do PDF

- **Papel:** A4 (595.28 × 841.89 pt)
- **Grade:** 3 colunas × 3 linhas = 9 cartas por folha
- **Tamanho da carta:** 63 × 88 mm (padrão MTG)
- **Marcas de corte:** cruzes cinzas + triângulos escuros em cada canto
- **Logo:** CardTrader centralizado no topo

### DFCs (Double-Faced Cards)

Cartas de frente e verso são extraídas para um PDF separado (`dfc_frente_verso.pdf`). As páginas de verso têm colunas espelhadas horizontalmente para que, ao imprimir em modo duplex **long-edge flip**, cada verso se alinhe perfeitamente com a frente correspondente.

```text
Frente: [A][B][_]     Verso:  [_][B'][A']
        [_][_][_]  →          [_][_][_]
        [_][_][_]             [_][_][_]
```

Quando há DFCs, o app retorna um ZIP com ambos os PDFs.

---

## Instalação

### Pré-requisitos

- Python 3.10+
- pip

```bash
cd mtg-craft
pip install -r requirements.txt
```

### Dependências

```text
flask>=3.0
pymupdf>=1.24
requests>=2.31
```

---

## Uso

```bash
python3 app.py
```

Acesse: <http://localhost:5001>

No Windows sem Python nativo, use WSL2:

```bat
wsl -e bash -c "cd /mnt/c/path/to/mtg-craft && python3 app.py"
```

Ou use o `start.bat` incluído.

---

## Import de Deck

### Formato texto (aba Lista)

```text
4 Lightning Bolt (M10) 146
1 Teferi, Hero of Dominaria (DOM) 207
1 Agadeem's Awakening / Agadeem, the Undercrypt (ZNR) 336
1 The Wise Mothman (SLD) 2455
4 Forest
```

Formatos aceitos: `Qty Nome (SET) Número`, `Qty Nome (SET) Número★`, DFCs com ` / `, ou apenas `Qty Nome`.

### URL de deck (aba Lista → "ou import por URL")

Cole diretamente a URL do deck:

- `https://www.moxfield.com/decks/AbCdEfGh12`
- `https://archidekt.com/decks/1234567`

O app busca o deck via API, importa todas as cartas automaticamente e pré-preenche o nome para salvar.

### URL de imagem (aba Upload)

Para cartas custom (MTGBuilder, proxies, arte alternativa):

1. Abra a aba **Upload**
2. Cole a URL direta da imagem no campo **"URL de imagem"**
3. Dê um nome (opcional) e clique em **↓ Adicionar Imagem**

---

## API

| Método | Endpoint | Descrição |
| --- | --- | --- |
| `GET` | `/api/search?q=<query>` | Busca no Scryfall |
| `GET` | `/api/card-by-set/<set>/<number>` | Busca carta exata |
| `POST` | `/api/upload` | Upload de imagem local |
| `GET` | `/api/thumb/<file>` | Thumbnail de upload |
| `POST` | `/api/generate` | Gera PDF (ou ZIP com DFCs) |
| `POST` | `/api/import-deck-url` | Import por URL (Moxfield, Archidekt) |
| `POST` | `/api/proxy-image` | Baixa imagem de URL externa |

---

## Estrutura

```text
mtg-craft/
├── app.py               # Backend Flask
├── generate.py          # Motor de geração de PDF (PyMuPDF)
├── requirements.txt
├── start.bat            # Atalho Windows/WSL2
├── logo_cardtrader.png  # Logo para o topo das folhas
└── static/
    ├── index.html       # Frontend SPA (tema MTG)
    └── logo_cardtrader.png
```

---

## Créditos

- Imagens de cartas: [Scryfall](https://scryfall.com) (uso não-comercial)
- Layout base: padrão de impressão CardTrader
- Fontes: [Cinzel](https://fonts.google.com/specimen/Cinzel) + [Inter](https://fonts.google.com/specimen/Inter) via Google Fonts

---

## Licença

MIT
