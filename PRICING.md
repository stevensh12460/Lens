# LENS Print Pricing Guide

**Location**: Hudson Valley, NY
**Last updated**: 2026-04-24
**Strategy**: Mid-range with room to scale. Positioned competitively against Anne Whitty ($95–$500 range) while signaling fine-art status on top-tier work.

---

## How Tiers Work

Pass3 runs `print_curator.py` which scores images 0–10 for print potential:

| Tier | Score Range | Edition | Positioning |
|---|---|---|---|
| **fine_art** | ≥ 8.5 | Limited (25 or 50) | Signed, numbered, certificate |
| **standard** | 7.0 – 8.4 | Open edition | Everyday catalog |
| **below_threshold** | < 7.0 | Not offered | Kept in archive only |

---

## STANDARD Tier — Open Edition

### Paper (archival pigment, museum-quality)
| Size | Price | Lab cost est. | Margin |
|---|---|---|---|
| 8x10  | **$75**  | ~$15 | $60 |
| 11x14 | **$110** | ~$22 | $88 |
| 16x20 | **$165** | ~$30 | $135 |
| 20x30 | **$260** | ~$54 | $206 |
| 24x36 | **$345** | ~$72 | $273 |

### Canvas Gallery Wrap (1.5" deep)
| Size | Price |
|---|---|
| 11x14 | **$200** |
| 16x20 | **$285** |
| 20x30 | **$420** |
| 24x36 | **$485** |

### Metal (aluminum, high-gloss or matte)
| Size | Price |
|---|---|
| 11x14 | **$225** |
| 16x20 | **$325** |
| 20x30 | **$475** |
| 24x36 | **$575** |

---

## FINE_ART Tier — Limited Edition

Each print **signed, numbered, and certificate of authenticity**. Edition size defaults to 25 for top-tier work, 50 for strong-but-not-rare.

### Paper (archival pigment)
| Size | Price |
|---|---|
| 11x14 | **$175** |
| 16x20 | **$250** |
| 20x30 | **$395** |
| 24x36 | **$525** |
| 40x60 | **$1,100** |

### Canvas Gallery Wrap
| Size | Price |
|---|---|
| 11x14 | **$300** |
| 16x20 | **$400** |
| 20x30 | **$575** |
| 24x36 | **$750** |
| 40x60 | **$1,450** |

### Metal
| Size | Price |
|---|---|
| 11x14 | **$350** |
| 16x20 | **$475** |
| 20x30 | **$675** |
| 24x36 | **$875** |
| 40x60 | **$1,750** |

---

## Market Comparisons

### Anne Whitty Photography (Hudson Valley, mid-tier)
Fine art paper: 16x20=$180, 20x30=$275, 24x36=$360
Canvas: 16x20=$300, 20x30=$440, 24x36=$500

### James Maher Photography (NYC, high-end)
24x36 = $625
40x60 = $1,250

### Pro Image NY (print cost only — your floor)
16x20 = $30 • 20x30 = $54 • 24x36 = $72

---

## Upload Workflow (Pixieset is manual)

Pixieset has no write API. Workflow:

1. **LENS scores** images for print potential (automatic via pass3)
2. **You review** via `/api/v1/print/candidates` endpoint (shows image + suggested prices per size)
3. **You upload** manually to Pixieset, copy the product URL
4. **You paste URL back** via dashboard → LENS marks `pixieset_url` and stops suggesting
5. **Revenue logging**: when a sale happens, log via `/api/v1/print/sale` (or import Pixieset CSV export)

---

## Sources & References

- Anne Whitty Photography (Hudson Valley)
- James Maher Photography (NYC)
- Pro Image NY (printing lab)
- Angelo Marcialis — Hudson Valley Landscape Photos
- PetaPixel pricing guide
