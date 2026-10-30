const STORAGE_KEY = "hallway-fire-inspection-history-v1";
export const MAX_HISTORY_ITEMS = 12;

const isValidItem = (item) =>
  item &&
  typeof item === "object" &&
  typeof item.id === "string" &&
  typeof item.thumbnail === "string" &&
  item.result &&
  typeof item.result.risk_level === "string";

export const loadHistory = () => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isValidItem).slice(0, MAX_HISTORY_ITEMS) : [];
  } catch {
    return [];
  }
};

export const persistHistory = (items) => {
  let list = items.slice(0, MAX_HISTORY_ITEMS);

  while (list.length > 0) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
      return list;
    } catch {
      list = list.slice(0, Math.max(0, list.length - 1));
    }
  }

  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failure
  }
  return [];
};

export const clearHistoryStorage = () => {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failure
  }
};
