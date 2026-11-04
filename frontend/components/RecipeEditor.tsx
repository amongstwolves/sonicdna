"use client";

import type { Meta } from "@/lib/api";
import { downloadJson } from "@/lib/download";
import {
  formatParam,
  fromPosition,
  getParam,
  setNodeEnabled,
  setParam,
  SLIDERS,
  SLIDER_STEPS,
  toPosition,
  type SliderDef,
} from "@/lib/recipe";
import { describeRecipe, formatLoss, type Recipe } from "@/lib/runs";

export function RecipeEditor({
  meta,
  recipe,
  baseName,
  baseLoss,
  edited,
  editLoss,
  notScoredReason,
  rendering,
  error,
  audioUrl,
  filenameStem,
  onChange,
  onReset,
}: {
  meta: Meta | null;
  recipe: Recipe | null;
  baseName: string;
  baseLoss: number | null;
  edited: boolean;
  editLoss: number | null;
  notScoredReason: string | null;
  rendering: boolean;
  error: string | null;
  audioUrl: string | null;
  filenameStem: string;
  onChange: (recipe: Recipe) => void;
  onReset: () => void;
}) {
  const renderable = recipe && typeof recipe.oscillator === "object";

  function slider(def: SliderDef) {
    if (!recipe || !meta) return null;
    const bounds = meta.recipe_bounds[def.path];
    const value = getParam(recipe, def.path);
    const toggleable = def.whenOn !== undefined;
    return (
      <div key={def.path} className="slider">
        <label htmlFor={def.path}>
          <span>
            {def.label}
            <small>{def.plain}</small>
          </span>
          <output className="mono">{value === null ? "Off" : formatParam(value, def.unit)}</output>
        </label>
        <div className="slider-row">
          <input
            id={def.path}
            type="range"
            min={0}
            max={SLIDER_STEPS}
            value={value === null ? 0 : toPosition(value, bounds, def.scale)}
            disabled={value === null}
            onChange={(event) =>
              onChange(setParam(recipe, def.path, fromPosition(Number(event.target.value), bounds, def.scale)))
            }
          />
          {toggleable ? (
            <label className="toggle compact">
              <input
                type="checkbox"
                checked={value !== null}
                aria-label={`${def.label} on`}
                onChange={(event) => onChange(setNodeEnabled(recipe, def, event.target.checked))}
              />
              On
            </label>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <section className="panel editor">
      <header>
        <div>
          <h2>Edit the recipe</h2>
          <p className="muted">
            Starting from {baseName}. Edits re-render on the server and are never added to the
            experiment log.
          </p>
        </div>
        <button type="button" className="button" onClick={onReset} disabled={!edited}>
          Reset
        </button>
      </header>
      {renderable ? (
        <>
          <p className="recipe-line">{describeRecipe(recipe)}</p>
          <div className="sliders">{SLIDERS.map(slider)}</div>
          <div className="edit-result" aria-live="polite">
            {error ? (
              <span className="failed-tag">{error}</span>
            ) : rendering ? (
              <span className="muted">Rendering your edit…</span>
            ) : edited ? (
              notScoredReason ? (
                <span className="muted">{notScoredReason}</span>
              ) : (
                <span>
                  <strong>Your edit</strong>: normalized loss{" "}
                  <span className="mono">{formatLoss(editLoss)}</span>{" "}
                  <span className="muted">
                    ({baseName}: <span className="mono">{formatLoss(baseLoss)}</span>. Lower is better.)
                  </span>
                </span>
              )
            ) : (
              <span className="muted">Move a slider to hear and measure a change.</span>
            )}
          </div>
          <div className="row">
            <button
              type="button"
              className="button"
              onClick={() => downloadJson(recipe, `${filenameStem}.json`)}
            >
              Download recipe (JSON)
            </button>
            {audioUrl ? (
              <a className="button" href={audioUrl} download={`${filenameStem}.wav`}>
                Download audio (WAV)
              </a>
            ) : null}
          </div>
        </>
      ) : (
        <p className="muted">This step has no recipe that can be edited.</p>
      )}
    </section>
  );
}
