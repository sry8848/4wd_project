"""QR-code decoding and project payload parsing.

The project payload format is ``TYPE:ID``. For reliable decoding on a
low-resolution camera, both fields intentionally use a compact uppercase ASCII
character set, for example ``TOLL:GATE1``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


QR_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]*$")
QR_IDENTIFIER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")


class QRCodeFormatError(ValueError):
    """Raised when decoded QR text does not follow the project format."""


class QRCodeRecognitionError(RuntimeError):
    """Raised when the OpenCV QR-code recognizer is unavailable."""


@dataclass(frozen=True)
class QRCodePayload:
    """Structured data decoded from a project QR code.

    Args:
        qr_type: Action or object type, such as ``TOLL``.
        identifier: Object identifier, such as ``GATE1``.
        raw_text: Original text stored in the QR code.
    """

    qr_type: str
    identifier: str
    raw_text: str


def parse_qr_payload(raw_text: str) -> QRCodePayload:
    """Parse and validate one ``TYPE:ID`` QR-code payload.

    Args:
        raw_text: Exact UTF-8 text decoded from a QR code.

    Returns:
        A validated, structured QRCodePayload.

    Raises:
        QRCodeFormatError: If the payload is empty, uses the wrong separator,
            or contains unsupported characters.
    """

    if not isinstance(raw_text, str) or not raw_text:
        raise QRCodeFormatError("QR code text is empty")

    # 1. Require exactly one ASCII colon so type and identifier are unambiguous.
    if raw_text.count(":") != 1:
        raise QRCodeFormatError("expected exactly one ASCII ':' separator")
    qr_type, identifier = raw_text.split(":", 1)

    # 2. Restrict both fields to compact characters that QR codes encode well.
    if not QR_TYPE_PATTERN.fullmatch(qr_type):
        raise QRCodeFormatError(
            "type must start with A-Z and contain only uppercase A-Z, "
            "digits, '-' or '_'"
        )
    if not QR_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise QRCodeFormatError(
            "identifier must contain only uppercase A-Z, digits, '-' or '_'"
        )

    # 3. Return structured data ready for a task or backend response.
    return QRCodePayload(
        qr_type=qr_type,
        identifier=identifier,
        raw_text=raw_text,
    )


class QRCodeRecognizer:
    """Decode QR text from OpenCV image frames.

    Args:
        detector: Optional OpenCV-compatible detector, mainly for dependency
            injection. When omitted, ``cv2.QRCodeDetector`` is created.
    """

    def __init__(self, detector: Optional[object] = None):
        if detector is not None:
            self._detector = detector
            return

        try:
            import cv2
        except ImportError as exc:
            raise QRCodeRecognitionError(
                "OpenCV is not installed; install python3-opencv first"
            ) from exc

        if not hasattr(cv2, "QRCodeDetector"):
            raise QRCodeRecognitionError(
                "This OpenCV build does not provide QRCodeDetector"
            )
        self._detector = cv2.QRCodeDetector()

    def decode(self, frame) -> List[str]:
        """Decode all readable QR-code texts in one image frame.

        Args:
            frame: OpenCV BGR or grayscale image.

        Returns:
            Unique, non-empty decoded texts in detection order.
        """

        if frame is None:
            raise ValueError("frame must not be None")

        # 1. Prefer the multi-code API when the installed OpenCV supports it.
        decoded_texts: List[str] = []
        decode_multi = getattr(self._detector, "detectAndDecodeMulti", None)
        if callable(decode_multi):
            result = decode_multi(frame)
            if len(result) >= 2 and result[0]:
                decoded_texts.extend(text for text in result[1] if text)

        # 2. Fall back to the widely supported single-code API.
        if not decoded_texts:
            text, _points, _straight_code = self._detector.detectAndDecode(frame)
            if text:
                decoded_texts.append(text)

        # 3. Avoid reporting the same decoded text twice from one frame.
        return list(dict.fromkeys(decoded_texts))
