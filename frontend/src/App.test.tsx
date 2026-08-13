import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the frontend foundation shell as semantic markup", () => {
    const markup = renderToStaticMarkup(<App />);

    expect(markup).toContain("<main");
    expect(markup).toContain("DataCheck");
    expect(markup).toContain("Frontend foundation");
    expect(markup).toContain("Product workflows belong to later increments.");
  });
});
