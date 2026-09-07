/**
 * Shared icon renderer for external system entries.
 * Accepts a base64 data-URI (from the new Upload flow) and falls back
 * to the ProviderIcon (legacy emoji) for backward compatibility.
 */
import React from "react";

interface Props {
  /** base64 data-URI from the new icon field, or legacy emoji string */
  icon?: string;
  /** system name (fallback for aria / alt) */
  name?: string;
  /** rendered size in px (default 28) */
  size?: number;
  /** extra inline styles */
  style?: React.CSSProperties;
}

export default function ExternalSystemIcon({ icon, name, size = 28, style }: Props) {
  // New format: base64 data-URI (starts with "data:image/")
  if (icon && icon.startsWith("data:image/")) {
    return (
      <img
        src={icon}
        alt={name || "system icon"}
        style={{
          width: size,
          height: size,
          borderRadius: 6,
          objectFit: "cover",
          flexShrink: 0,
          ...style,
        }}
      />
    );
  }
  // Legacy: emoji string
  return (
    <span style={{ fontSize: size, lineHeight: 1, ...style }}>
      {icon || "🔗"}
    </span>
  );
}
