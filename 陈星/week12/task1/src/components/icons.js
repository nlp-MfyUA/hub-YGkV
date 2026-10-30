import React from "react";

const Svg = ({ children, size = 20, className = "", strokeWidth = 1.8, ...rest }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden="true"
    {...rest}
  >
    {children}
  </svg>
);

export const ShieldIcon = (props) => (
  <Svg {...props}>
    <path d="M12 3 19 6v5.2c0 4.4-2.9 7.5-7 9.3-4.1-1.8-7-4.9-7-9.3V6l7-3Z" />
    <path d="M12 16.6c-1.7-.9-2.6-2.3-2.6-3.8 0-1.4 1.2-2.4 2.6-1.1 1.4-1.3 2.6-.3 2.6 1.1 0 1.5-.9 2.9-2.6 3.8Z" />
  </Svg>
);

export const CameraIcon = (props) => (
  <Svg {...props}>
    <path d="M4 8h3l1.6-2.2h6.8L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" />
    <circle cx="12" cy="13" r="3.4" />
  </Svg>
);

export const UploadIcon = (props) => (
  <Svg {...props}>
    <path d="M12 16V4" />
    <path d="m7 9 5-5 5 5" />
    <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </Svg>
);

export const RefreshIcon = (props) => (
  <Svg {...props}>
    <path d="M20 11a8 8 0 1 0-2.4 5.7" />
    <path d="M20 5v6h-6" />
  </Svg>
);

export const SwitchCameraIcon = (props) => (
  <Svg {...props}>
    <path d="M4 8h13l-3-3" />
    <path d="M20 16H7l3 3" />
  </Svg>
);

export const AlertIcon = (props) => (
  <Svg {...props}>
    <path d="M10.3 4.6 2.9 17.4A1.6 1.6 0 0 0 4.3 20h15.4a1.6 1.6 0 0 0 1.4-2.6L13.7 4.6a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4" />
    <path d="M12 16.5h.01" />
  </Svg>
);

export const CheckCircleIcon = (props) => (
  <Svg {...props}>
    <circle cx="12" cy="12" r="9" />
    <path d="m8.5 12.2 2.4 2.4 4.7-5" />
  </Svg>
);

export const XCircleIcon = (props) => (
  <Svg {...props}>
    <circle cx="12" cy="12" r="9" />
    <path d="m9 9 6 6" />
    <path d="m15 9-6 6" />
  </Svg>
);

export const MinusCircleIcon = (props) => (
  <Svg {...props}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8.5 12h7" />
  </Svg>
);

export const SparklesIcon = (props) => (
  <Svg {...props}>
    <path d="M12 3.5 13.6 9 19 10.6 13.6 12.2 12 17.7 10.4 12.2 5 10.6 10.4 9 12 3.5Z" />
    <path d="M18.5 16.5 19.2 19l2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.5Z" />
  </Svg>
);

export const ScanIcon = (props) => (
  <Svg {...props}>
    <path d="M4 8V5a1 1 0 0 1 1-1h3" />
    <path d="M16 4h3a1 1 0 0 1 1 1v3" />
    <path d="M20 16v3a1 1 0 0 1-1 1h-3" />
    <path d="M8 20H5a1 1 0 0 1-1-1v-3" />
    <path d="M4 12h16" />
  </Svg>
);

export const ArrowRightIcon = (props) => (
  <Svg {...props}>
    <path d="M4 12h16" />
    <path d="m14 6 6 6-6 6" />
  </Svg>
);

export const CloseIcon = (props) => (
  <Svg {...props}>
    <path d="m6 6 12 12" />
    <path d="m18 6-12 12" />
  </Svg>
);

export const ImageIcon = (props) => (
  <Svg {...props}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="8.5" cy="9.5" r="1.5" />
    <path d="m4 17 5-4.5 4 3.5 3-2.5 4 3.5" />
  </Svg>
);

export const BuildingIcon = (props) => (
  <Svg {...props}>
    <path d="M4 21V6.5L12 3v18" />
    <path d="M12 9h8v12" />
    <path d="M7.5 8.5h1.5M7.5 12h1.5M7.5 15.5h1.5M15 12.5h1.5M15 16h1.5" />
    <path d="M2 21h20" />
  </Svg>
);

export const FlameIcon = (props) => (
  <Svg {...props}>
    <path d="M12 21c3.6 0 6-2.3 6-5.5 0-2.6-1.7-4.4-3.2-6.1-.6 1.5-1.4 2.6-2.8 3.3.2-3-1.3-6.1-4-7.7.2 3.2-2 5-2 8.1C6 18.2 8.5 21 12 21Z" />
    <path d="M12 21c-1.7 0-2.8-1.1-2.8-2.6 0-1.5 1.2-2.7 2.8-4.4 1.6 1.7 2.8 2.9 2.8 4.4 0 1.5-1.1 2.6-2.8 2.6Z" />
  </Svg>
);

export const InfoIcon = (props) => (
  <Svg {...props}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5" />
    <path d="M12 7.8h.01" />
  </Svg>
);
