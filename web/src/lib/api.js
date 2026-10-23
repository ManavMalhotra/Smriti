export class ApiError extends Error {
  constructor(message, status = 0, code = null, data = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      ...options,
    });
  } catch {
    throw new ApiError(
      "Could not reach the local server. Check that it is running and try again.",
    );
  }

  let data = null;
  if (response.status !== 204) {
    try {
      data = await response.json();
    } catch {
      // A non-JSON body is treated as a generic failure below.
    }
  }

  if (!response.ok) {
    throw new ApiError(
      data?.error?.message ?? "The request failed. Try again.",
      response.status,
      data?.error?.code,
      data,
    );
  }
  return data;
}
