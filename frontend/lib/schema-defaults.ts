import type { JsonSchema } from "@/lib/types";

/**
 * Builds an example payload from a JSON schema: only required fields are
 * included (nested objects recurse), using `default`/`examples`/`enum` where
 * available, otherwise a type-appropriate placeholder.
 */
export function schemaDefaults(schema: JsonSchema | null | undefined): Record<string, unknown> {
  if (!schema) return {};
  const value = buildValue(schema, schema, 0);
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function resolveRef(root: JsonSchema, ref: string): JsonSchema | null {
  if (!ref.startsWith("#/")) return null;
  const parts = ref.slice(2).split("/");
  let current: unknown = root;
  for (const part of parts) {
    if (!isRecord(current)) return null;
    current = current[part];
  }
  return isRecord(current) ? (current as JsonSchema) : null;
}

function deref(root: JsonSchema, schema: JsonSchema): JsonSchema {
  if (schema.$ref) {
    const resolved = resolveRef(root, schema.$ref);
    if (resolved) return { ...resolved, ...omitRef(schema) };
  }
  return schema;
}

function omitRef(schema: JsonSchema): JsonSchema {
  const { $ref: _ref, ...rest } = schema;
  return rest;
}

function pickVariant(root: JsonSchema, variants: JsonSchema[]): JsonSchema | null {
  const concrete = variants.map((v) => deref(root, v)).filter((v) => v.type !== "null");
  return concrete[0] ?? null;
}

function buildValue(root: JsonSchema, raw: JsonSchema, depth: number): unknown {
  if (depth > 6) return null;
  const schema = deref(root, raw);
  if (schema.default !== undefined) return schema.default;
  if (Array.isArray(schema.examples) && schema.examples.length > 0) return schema.examples[0];
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return schema.enum[0];

  const union = schema.anyOf ?? schema.oneOf;
  if (union && union.length > 0) {
    const variant = pickVariant(root, union);
    return variant ? buildValue(root, variant, depth + 1) : null;
  }
  if (schema.allOf && schema.allOf.length > 0) {
    const merged = schema.allOf.reduce<JsonSchema>((acc, part) => ({ ...acc, ...deref(root, part) }), {});
    return buildValue(root, { ...merged, allOf: undefined }, depth + 1);
  }

  const type = Array.isArray(schema.type) ? schema.type.find((t) => t !== "null") : schema.type;
  switch (type) {
    case "object": {
      const result: Record<string, unknown> = {};
      const required = schema.required ?? [];
      const properties = schema.properties ?? {};
      for (const key of required) {
        const prop = properties[key];
        result[key] = prop ? buildValue(root, prop, depth + 1) : null;
      }
      return result;
    }
    case "array":
      return [];
    case "string":
      if (schema.format === "date-time") return new Date().toISOString();
      if (schema.format === "email") return "user@example.test";
      return "";
    case "integer":
    case "number":
      return typeof schema.minimum === "number" ? schema.minimum : 0;
    case "boolean":
      return false;
    case "null":
      return null;
    default:
      if (schema.properties) {
        return buildValue(root, { ...schema, type: "object" }, depth);
      }
      return null;
  }
}

/** Flattened list of top-level fields for documentation tables. */
export interface SchemaField {
  name: string;
  type: string;
  required: boolean;
  description?: string;
}

export function schemaFields(schema: JsonSchema | null | undefined): SchemaField[] {
  if (!schema?.properties) return [];
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties).map(([name, raw]) => {
    const prop = deref(schema, raw);
    return { name, type: describeType(schema, prop), required: required.has(name), description: prop.description };
  });
}

function describeType(root: JsonSchema, schema: JsonSchema): string {
  const union = schema.anyOf ?? schema.oneOf;
  if (union) return union.map((v) => describeType(root, deref(root, v))).join(" | ");
  if (schema.$ref) return schema.$ref.split("/").pop() ?? "object";
  if (Array.isArray(schema.type)) return schema.type.join(" | ");
  if (schema.type === "array" && schema.items) return `${describeType(root, deref(root, schema.items))}[]`;
  if (schema.enum) return schema.enum.map((e) => JSON.stringify(e)).join(" | ");
  return schema.type ?? (schema.properties ? "object" : "any");
}
