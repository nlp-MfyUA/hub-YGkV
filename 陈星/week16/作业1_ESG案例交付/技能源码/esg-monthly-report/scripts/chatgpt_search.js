(async (plan) => {
  // Run in ChatGPT code mode. Only this installed file is evaluated as JavaScript.
  const browser = tools.mcp__codex_apps__search_service_web_run;
  const groups = (result) => (result?.content ?? [])
    .filter((block) => block.type === "text")
    .flatMap((block) => block.text.split(/\n-{8,}\n/));

  function heading(part) {
    const lines = part.trim().split("\n");
    const match = lines[0]?.match(/^(.*?)\s*\((https?:\/\/[^\s]+)\)$/);
    const ref = lines[1]?.match(/【([^】]+)】/)?.[1];
    return match && ref ? { title: match[1].trim(), url: match[2], ref } : null;
  }

  async function inBatches(items, size, operation) {
    const results = [];
    for (let start = 0; start < items.length; start += size) {
      results.push(...await Promise.allSettled(items.slice(start, start + size).map(operation)));
    }
    return results;
  }

  const errors = [];
  const discovery = await inBatches(plan.queries, 4, async ({ query }) => {
    const result = await browser({
      system2_search_query: [{ q: query }], n_results: 5, n_tokens: 1800,
    });
    if (result.isError) throw new Error("search returned an error");
    return groups(result).map(heading).filter((item) => item !== null);
  });

  const unique = new Map();
  const maxDepth = Math.max(0, ...discovery.map((result) =>
    result.status === "fulfilled" ? result.value.length : 0));
  discovery.forEach((result, index) => {
    if (result.status === "rejected") {
      errors.push({ lane: plan.queries[index].lane, query: plan.queries[index].query, step: "search" });
    }
  });

  for (let rank = 0; rank < maxDepth; rank++) {
    for (let i = 0; i < discovery.length; i++) {
      const view = discovery[i];
      if (view.status !== "fulfilled" || !view.value[rank]) continue;
      const candidate = view.value[rank];
      if (!unique.has(candidate.url)) {
        unique.set(candidate.url, { ...candidate, lane: plan.queries[i].lane });
      }
    }
  }

  const selected = [...unique.values()].slice(0, plan.max_open);
  const opened = await inBatches(selected, 4, async (item) => {
    const result = await browser({ open: [{ ref_id: item.ref }], n_tokens: 2400 });
    if (result.isError) throw new Error("open returned an error");
    const pieces = groups(result);
    const part = pieces[0] ?? "";
    const sourceLines = part.split("\n").filter((line) => /^L\d+(?:@P\d+)?:/.test(line));
    let previous;
    let gap = false;
    for (const line of sourceLines) {
      const number = Number(line.match(/^L(\d+)/)[1]);
      if (previous !== undefined && number !== previous + 1) gap = true;
      previous = number;
    }
    const body = sourceLines.map((line) => line.replace(/^L\d+(?:@P\d+)?:\s?/, "")).join("\n").trim();
    const lines = body.split("\n");
    const title = lines.find((line) => /^#{1,3}\s+.{9,}/.test(line))?.replace(/^#+\s+/, "");
    const firstLine = lines.find((line) => /^[\p{L}].{9,90}$/u.test(line) && !line.includes("【"));
    const openedTitle = heading(part);
    return {
      ...item,
      title: item.title && !/^(?:[\w.-]+\.cn|.{1,12}(?:交易网|采购网|招标平台))$/.test(item.title)
        ? item.title : title || firstLine || item.title || item.url,
      url: openedTitle?.url ?? item.url,
      ref: openedTitle?.ref ?? item.ref,
      text: body,
      outcome: body ? "opened" : "unavailable",
      gap,
    };
  });
  let openedCount = 0;
  const documents = opened.map((result, index) => {
    const empty = { ...selected[index], text: "", outcome: "unavailable" };
    const doc = result.status === "fulfilled" ? result.value : empty;
    if (doc.outcome === "opened") openedCount++;
    else errors.push({ lane: doc.lane, url: doc.url, step: "open" });
    return { ...doc, id: `W${String(index + 1).padStart(2, "0")}` };
  });
  return {
    profile: plan.profile,
    queries: plan.queries,
    documents,
    errors,
    coverage: { candidate_count: unique.size, open_attempted: selected.length, opened_count: openedCount },
  };
})
