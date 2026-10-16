import { render, screen } from "@testing-library/react";
import App from "./App";

test("rendert die leere Seite", () => {
  render(<App />);
  expect(screen.getByRole("main", { name: "Cat" })).toBeInTheDocument();
});
