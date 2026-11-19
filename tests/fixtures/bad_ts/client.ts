import OpenAI from "openai";
// Browser-side client: the key ships in the bundle.
export const client = new OpenAI({ apiKey: process.env.NEXT_PUBLIC_OPENAI_API_KEY, dangerouslyAllowBrowser: true });
