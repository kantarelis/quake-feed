import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useFilters, type AlertFilterRow } from "../hooks/useFilters";
import {
  buildFilter,
  describeFilter,
  EMPTY_FORM,
  type FilterFormState,
  type FilterShape,
} from "./alertFilterForm";

const SHAPES: { value: FilterShape; label: string }[] = [
  { value: "none", label: "Magnitude only" },
  { value: "bbox", label: "Bounding box" },
  { value: "center", label: "Center + radius" },
];

function NumberField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-600">
        {label}
      </label>
      <input
        id={id}
        type="number"
        step="any"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:outline-none"
      />
    </div>
  );
}

function FilterRow({
  filter,
  onDelete,
}: {
  filter: AlertFilterRow;
  onDelete: (id: number) => void;
}) {
  return (
    <li className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <span className="min-w-0 truncate text-sm text-slate-700">{describeFilter(filter)}</span>
      <button
        type="button"
        onClick={() => onDelete(filter.id)}
        className="shrink-0 rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-red-50 hover:text-red-700"
      >
        Delete
      </button>
    </li>
  );
}

/** Create / list / delete the authenticated key's alert filters. */
export function AlertConfig() {
  const { filters, loading, error, create, remove } = useFilters();
  const [form, setForm] = useState<FilterFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function update<K extends keyof FilterFormState>(key: K, value: FilterFormState[K]): void {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const result = buildFilter(form);
    if (!result.ok) {
      setFormError(result.error);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await create(result.body);
      setForm(EMPTY_FORM);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to create filter.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number): Promise<void> {
    setDeleteError(null);
    try {
      await remove(id);
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Failed to delete filter.");
    }
  }

  const hasFilters = filters.length > 0;
  const listError = error ?? deleteError;

  return (
    <section className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Alert filters</h1>
        <p className="mt-1 text-sm text-slate-500">
          Each filter is a minimum magnitude and/or one geographic shape. The SSE stream delivers
          events matching any of them.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
      >
        <NumberField
          id="filter-min-magnitude"
          label="Minimum magnitude (optional)"
          value={form.minMagnitude}
          onChange={(value) => update("minMagnitude", value)}
        />

        <fieldset className="flex flex-col gap-2">
          <legend className="text-xs font-medium text-slate-600">Geographic shape</legend>
          <div className="flex flex-wrap gap-4">
            {SHAPES.map((shape) => (
              <label key={shape.value} className="flex items-center gap-1.5 text-sm text-slate-700">
                <input
                  type="radio"
                  name="shape"
                  value={shape.value}
                  checked={form.shape === shape.value}
                  onChange={() => update("shape", shape.value)}
                />
                {shape.label}
              </label>
            ))}
          </div>
        </fieldset>

        {form.shape === "bbox" ? (
          <div className="grid grid-cols-2 gap-3">
            <NumberField
              id="bbox-min-lat"
              label="Min latitude"
              value={form.bboxMinLat}
              onChange={(value) => update("bboxMinLat", value)}
            />
            <NumberField
              id="bbox-min-lon"
              label="Min longitude"
              value={form.bboxMinLon}
              onChange={(value) => update("bboxMinLon", value)}
            />
            <NumberField
              id="bbox-max-lat"
              label="Max latitude"
              value={form.bboxMaxLat}
              onChange={(value) => update("bboxMaxLat", value)}
            />
            <NumberField
              id="bbox-max-lon"
              label="Max longitude"
              value={form.bboxMaxLon}
              onChange={(value) => update("bboxMaxLon", value)}
            />
          </div>
        ) : null}

        {form.shape === "center" ? (
          <div className="grid grid-cols-3 gap-3">
            <NumberField
              id="center-lat"
              label="Center latitude"
              value={form.centerLat}
              onChange={(value) => update("centerLat", value)}
            />
            <NumberField
              id="center-lon"
              label="Center longitude"
              value={form.centerLon}
              onChange={(value) => update("centerLon", value)}
            />
            <NumberField
              id="center-radius"
              label="Radius (km)"
              value={form.radiusKm}
              onChange={(value) => update("radiusKm", value)}
            />
          </div>
        ) : null}

        {formError ? (
          <p
            role="alert"
            className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
          >
            {formError}
          </p>
        ) : null}

        <div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {submitting ? "Adding…" : "Add filter"}
          </button>
        </div>
      </form>

      <div>
        <h2 className="text-lg font-semibold text-slate-900">Current filters</h2>
        <div className="mt-3">
          {listError ? (
            <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {listError}
            </p>
          ) : loading && !hasFilters ? (
            <p className="text-sm text-slate-500">Loading filters…</p>
          ) : !hasFilters ? (
            <p className="text-sm text-slate-500">No filters yet — add one above.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {filters.map((filter) => (
                <FilterRow key={filter.id} filter={filter} onDelete={handleDelete} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
