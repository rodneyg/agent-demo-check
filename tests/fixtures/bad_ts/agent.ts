async function run() {
  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST", body: JSON.stringify({input: "Hello"})
  });
  const data = JSON.parse(await response.text());
  return data;
}
