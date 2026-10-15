import { useEffect, useState } from "react";
import { api } from "../auth/bff.js";

// Which LLM the assistant / AI wording uses: the models configured on the server
// (GET /v1/llm/providers), e.g. Azure OpenAI or the university cluster. Remembered per device.
const KEY = "fea.llm.provider";

function stored() {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function useModelChoice() {
  const [providers, setProviders] = useState([]);
  const [choice, setChoice] = useState(stored);

  useEffect(() => {
    let alive = true;
    api("/v1/llm/providers")
      .then((list) => { if (alive) setProviders(list); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const valid = providers.some((p) => p.id === choice);
  const value = valid ? choice : (providers.find((p) => p.default) || providers[0])?.id || null;
  const change = (id) => {
    setChoice(id);
    try {
      localStorage.setItem(KEY, id);
    } catch {
      /* private mode: the choice just isn't remembered */
    }
  };
  return { providers, value, change };
}
