import { useCallback, useEffect, useState } from "react";
import { loadYolo, reloadYolo, subscribeYolo } from "../utils/yolo";

const INITIAL_STATUS = {
  status: "loading",
  text: "正在准备本地检测引擎…",
  progress: 0,
};

export const useYolo = () => {
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const unsubscribe = subscribeYolo((next) => {
      if (active) setStatus(next);
    });

    const promise = attempt === 0 ? loadYolo() : reloadYolo();
    promise
      .then((nextSession) => {
        if (active) setSession(nextSession);
      })
      .catch(() => {
        if (active) setSession(null);
      });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setSession(null);
    setStatus(INITIAL_STATUS);
    setAttempt((value) => value + 1);
  }, []);

  return { session, status, retry };
};
