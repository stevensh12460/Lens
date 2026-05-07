"""
CRM — Contract template management.
No LLM calls. All DB access through core/database.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.config import settings
from core.database import get_db


# ---------------------------------------------------------------------------
# Contract templates
# ---------------------------------------------------------------------------

_BASE_FOOTER = """
---
SIGNATURES

Photographer: {photographer_name} / {business_name}
Client: {client_name}
Date Signed: {date_signed}

By engaging services, the client acknowledges reading, understanding, and agreeing
to all terms stated above. This agreement is binding upon signature or written
confirmation via email.
"""

CONTRACTS: dict[str, str] = {
    "wedding": """
WEDDING PHOTOGRAPHY AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Wedding Date: {shoot_date}
Venue / Location: {location}
Package: {package}
Total Investment: ${amount}
Retainer (Non-Refundable): ${deposit}

1. SERVICES
The Photographer agrees to provide wedding photography coverage on the date and at
the location specified above, as outlined in the selected package.

2. RETAINER & PAYMENT
A non-refundable retainer of ${deposit} is due upon signing to secure the date.
The remaining balance of ${balance} is due no later than 14 days before the
wedding date. Failure to pay the remaining balance by the due date may result in
cancellation of services without refund of the retainer.

3. CANCELLATION & RESCHEDULING
Cancellations made more than 90 days before the wedding date will result in
forfeiture of the retainer only. Cancellations within 90 days may result in
the full contract amount becoming due. Rescheduling requests are subject to
availability and must be made in writing.

4. DELIVERABLES
Final edited images will be delivered within 8–12 weeks of the wedding date via
a private online gallery. The number of delivered images will vary based on the
day's events.

5. COPYRIGHT & USAGE
The Photographer retains copyright of all images. The client is granted a
personal-use license for printing and sharing. Commercial use requires written
permission. The Photographer reserves the right to use images for portfolio,
social media, and marketing purposes unless a privacy agreement is in place.

6. FORCE MAJEURE
In the event of illness, injury, or emergency preventing the Photographer from
fulfilling this contract, every effort will be made to arrange a qualified
substitute. If no substitute is available, the Photographer's liability is
limited to a full refund of all payments received.

7. LIMITATION OF LIABILITY
The Photographer's liability is limited to the total amount paid under this
agreement. The Photographer is not responsible for lost images due to equipment
failure, weather, or circumstances beyond their control.
""" + _BASE_FOOTER,

    "portrait": """
PORTRAIT PHOTOGRAPHY AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Session Date: {shoot_date}
Location: {location}
Package: {package}
Total Investment: ${amount}
Retainer: ${deposit}

1. SERVICES
The Photographer agrees to provide a portrait photography session on the date and
at the location specified above.

2. PAYMENT
A retainer of ${deposit} is due upon signing to confirm the session. The
remaining balance is due on or before the session date. Sessions will not
begin until payment is received in full.

3. CANCELLATION
Cancellations or rescheduling requests must be made at least 48 hours in advance.
Late cancellations forfeit the retainer. Rescheduling is subject to availability.

4. DELIVERABLES
Edited images will be delivered within 2–3 weeks via a password-protected online
gallery. The estimated number of final images is outlined in the selected package.

5. COPYRIGHT & USAGE
The Photographer retains copyright of all images. The client receives a
personal-use license. Commercial use requires a separate licensing agreement.

6. WEATHER & OUTDOOR SESSIONS
Outdoor sessions may be rescheduled due to inclement weather at no penalty to
either party.
""" + _BASE_FOOTER,

    "boudoir": """
BOUDOIR PHOTOGRAPHY AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Session Date: {shoot_date}
Location: {location}
Package: {package}
Total Investment: ${amount}
Retainer: ${deposit}

PRIVACY NOTICE: All information in this agreement and all images produced are
treated with strict confidentiality.

1. SERVICES
The Photographer agrees to provide a boudoir photography session as described
in the selected package. All sessions are conducted professionally in a safe,
respectful, and private environment.

2. PAYMENT
A retainer of ${deposit} is due upon signing. Remaining balance is due on the
session date. All transactions are discreet.

3. PRIVACY & CONFIDENTIALITY
All images are stored securely. The Photographer will NOT share, publish, or
use any images from this session for any purpose without the client's explicit
written consent. Gallery access is PIN-protected.

4. MODEL RELEASE (Optional)
If the client wishes to grant portfolio/marketing use, a separate model release
form will be signed. Absence of a signed release means no images will be used
publicly under any circumstances.

5. CANCELLATION
48-hour advance notice required for rescheduling. Late cancellations forfeit
the retainer.

6. DELIVERABLES
Edited images delivered within 2–3 weeks via private PIN-protected gallery.
""" + _BASE_FOOTER,

    "commercial": """
COMMERCIAL PHOTOGRAPHY AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Shoot Date: {shoot_date}
Location: {location}
Package / Project: {package}
Total Investment: ${amount}
Retainer: ${deposit}

1. SCOPE OF WORK
The Photographer agrees to provide commercial photography services as described
in the project brief. Final deliverables and image count are as agreed upon
in writing.

2. USAGE RIGHTS
Images are licensed for the specific usage rights outlined in the project brief.
Usage beyond the agreed scope requires a separate licensing agreement. The
Photographer retains copyright in all circumstances.

3. PAYMENT TERMS
50% retainer due upon signing. Remaining 50% (${balance}) due upon delivery
of final edited images. Late payments accrue interest at 1.5% per month.

4. CANCELLATION
Cancellation within 7 business days of the shoot date will result in the full
contract amount becoming due to cover time and preparation costs.

5. DELIVERABLES & TIMELINE
Final edited images delivered within 5–10 business days unless otherwise agreed.
Rush delivery available at additional cost.

6. EXCLUSIVITY
The Photographer reserves the right to use non-confidential images for portfolio
purposes unless a non-disclosure agreement is separately executed.
""" + _BASE_FOOTER,

    "events": """
EVENT PHOTOGRAPHY AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Event Date: {shoot_date}
Venue: {location}
Package: {package}
Total Investment: ${amount}
Retainer: ${deposit}

1. SERVICES
The Photographer will provide event photography coverage for the hours and
coverage area specified in the package.

2. PAYMENT
Retainer of ${deposit} due upon signing. Balance due one week before the event.

3. CANCELLATION
Cancellations more than 30 days out forfeit only the retainer. Within 30 days,
the full amount becomes due.

4. DELIVERABLES
Edited images delivered via online gallery within the turnaround period specified
at booking. Turnaround for standard events is 1–2 weeks.

5. ACCESS & COOPERATION
Client is responsible for ensuring the Photographer has full access to all areas
and events that require coverage. The Photographer is not responsible for missed
moments due to restricted access.

6. COPYRIGHT
The Photographer retains copyright. Client receives a license for internal and
promotional use only unless otherwise agreed.
""" + _BASE_FOOTER,

    "nature": """
NATURE & LANDSCAPE PHOTOGRAPHY AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Shoot Date: {shoot_date}
Location: {location}
Package: {package}
Total Investment: ${amount}
Retainer: ${deposit}

1. SERVICES
The Photographer will provide nature / landscape photography services as agreed.

2. PAYMENT
Retainer of ${deposit} due upon booking. Balance due before delivery of images.

3. WEATHER & CONDITIONS
Nature photography is subject to weather, lighting, and environmental conditions
beyond anyone's control. The Photographer will make every effort to capture
compelling images. Sessions may be rescheduled due to severe weather at no penalty.

4. USAGE RIGHTS
Usage rights as specified at booking. Personal use included. Commercial licensing
requires a separate agreement.

5. DELIVERABLES
Final edited images delivered within 1–2 weeks via online gallery.
""" + _BASE_FOOTER,
}

# Fallback for unknown genres
_DEFAULT_CONTRACT = """
PHOTOGRAPHY SERVICES AGREEMENT

Photographer: {photographer_name}
Business: {business_name}
Client: {client_name}
Shoot Date: {shoot_date}
Location: {location}
Package: {package}
Total Investment: ${amount}
Retainer: ${deposit}

1. SERVICES
The Photographer agrees to provide photography services as discussed and agreed.

2. PAYMENT
A retainer is due upon signing to secure the date. The remaining balance is due
before or on the shoot date.

3. CANCELLATION
Retainer is non-refundable. Please provide at least 48 hours notice for
rescheduling requests.

4. DELIVERABLES
Final edited images will be delivered via online gallery within the agreed
timeframe.

5. COPYRIGHT
The Photographer retains copyright of all images. The client receives a
personal-use license unless otherwise specified.
""" + _BASE_FOOTER


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def get_contract_template(genre: str) -> str:
    """Return the raw contract template string for the given genre."""
    return CONTRACTS.get(genre.lower(), _DEFAULT_CONTRACT)


def generate_contract(booking_id: int) -> Optional[str]:
    """
    Pull booking + client data, fill template placeholders, return contract text.
    Returns None if booking not found.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT b.*, c.name as client_name, s.location
               FROM bookings b
               JOIN clients c ON b.client_id = c.id
               LEFT JOIN shoots s ON b.shoot_id = s.id
               WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
        if not row:
            return None
        booking = dict(row)

    amount = booking.get("amount") or 0
    deposit = round(amount * 0.5, 2)
    balance = round(amount - deposit, 2)

    template = get_contract_template(booking.get("genre", ""))

    context = {
        "client_name":       booking.get("client_name", ""),
        "shoot_date":        str(booking.get("shoot_date", "")),
        "location":          booking.get("location") or "TBD",
        "package":           booking.get("package") or "Custom Package",
        "amount":            f"{amount:,.2f}",
        "deposit":           f"{deposit:,.2f}",
        "balance":           f"{balance:,.2f}",
        "photographer_name": settings.photographer_name,
        "business_name":     settings.business_name or settings.photographer_name,
        "date_signed":       datetime.now().strftime("%B %d, %Y"),
    }

    return template.format(**context)


def save_signed_contract(
    booking_id: int,
    signed_by: str,
    signed_at: Optional[str] = None,
) -> dict:
    """
    Mark contract_signed = True, save signed_by and signed_at to booking.
    signed_at defaults to now if not provided.
    """
    if not signed_at:
        signed_at = datetime.now().isoformat()

    with get_db() as conn:
        conn.execute(
            """UPDATE bookings
               SET contract_signed = TRUE, signed_by = ?, signed_at = ?
               WHERE id = ?""",
            (signed_by, signed_at, booking_id),
        )
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else {}
