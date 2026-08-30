import "@testing-library/jest-dom/vitest";
import { Browser } from "leaflet";

/**
 * Enable Leaflet's SVG renderer under jsdom.
 *
 * Leaflet probes for SVG support with `createSVGRect`, which jsdom does not
 * implement, so it disables its only vector renderer and every route polyline
 * throws on mount. Real browsers always pass that probe, and the renderer
 * itself only creates elements and sets attributes, so forcing the flag makes
 * these tests exercise the same rendering path the application ships.
 */
(Browser as unknown as { svg: boolean }).svg = true;
