import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";

import { commandApi } from "@/services/api";
import { useWebSocket } from "@/hooks/useWebSocket";

interface FunctionCall {
  name: string;
  arguments: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  functionCall?: FunctionCall;
}

interface CommandCenterProps {}

export const CommandCenter: React.FC<CommandCenterProps> = () => {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { socket, connected } = useWebSocket();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [usingDemo, setUsingDemo] = useState(false);

  // Check Ollama health
  useEffect(() => {
    const checkOllama = async () => {
      try {
        const res = await commandApi.health();
        setUsingDemo(!res.data.available);
      } catch {
        setUsingDemo(true);
      }
    };

    checkOllama();

    const interval = setInterval(checkOllama, 60000);
    return () => clearInterval(interval);
  }, []);

  const sendQuery = async (query: string) => {
    const trimmedQuery = query.trim();

    if (!trimmedQuery || isThinking) {
      return;
    }

    setIsThinking(true);

    const userMessage: Message = {
      role: "user",
      content: trimmedQuery,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);

    try {
      const res = await commandApi.query({ user_query: trimmedQuery });

      const functionCalls = Array.isArray(res.data.function_calls)
        ? res.data.function_calls
        : [];

      const firstFunctionCall: FunctionCall | undefined =
        functionCalls.length > 0 ? functionCalls[0] : undefined;

      const assistantMessage: Message = {
        role: "assistant",
        content: res.data.response || "No response received.",
        timestamp: new Date(),
        functionCall: firstFunctionCall,
      };

      setMessages((prev) => [...prev, assistantMessage]);

      if (firstFunctionCall) {
        toast.info(`Function called: ${firstFunctionCall.name}`);
      }

      // Emit via WebSocket if connected
      if (socket && res.data.response) {
        try {
          await socket.emit("command_interaction", {
            event: "command_interaction",
            data: {
              query: trimmedQuery,
              response: res.data.response,
            },
          });
        } catch {
          // WebSocket notification is not critical.
        }
      }

      // Handle function call results
      if (firstFunctionCall) {
        // Could trigger specific UI updates based on function called
        const fnName = firstFunctionCall.name;
        const fnArgs = firstFunctionCall.arguments;

        if (fnName === "get_incident_priority") {
          // Priority already shown in response
        } else if (fnName === "assign_resources") {
          // Resources assigned - could show toast
          toast.success("Resources assigned to incident");
        } else if (fnName === "run_prediction") {
          // Prediction result - could navigate to What-If view
          toast.info("Prediction simulation started");
        } else if (fnName === "list_available_resources") {
          // Show available resources
        }
      }
    } catch (err: unknown) {
      setUsingDemo(true);

      let errorMessage = "Command failed";

      if (axios.isAxiosError(err)) {
        errorMessage =
          err.response?.data?.detail ||
          err.response?.data?.message ||
          err.message ||
          errorMessage;
      }

      toast.error(errorMessage);

      // Demo mode fallback responses
      const demoResponses: Record<string, string> = {
        "what's the status":
          "Demo mode: Vadodara flood zone - Priority 78/100, 5 victims, 3 teams assigned",

        "critical incidents":
          "Demo mode: 2 incidents above priority 70",

        "available teams":
          "Demo mode: 8 teams available across 3 zones",

        "fire prediction":
          "Demo mode: Fire spread simulation for Vadodara zone",

        "my incidents":
          "Demo mode: Showing your active incidents",
      };

      const lowered = trimmedQuery.toLowerCase();

      const demoKey = Object.keys(demoResponses).find((key) =>
        lowered.includes(key)
      );

      if (demoKey) {
        const demoMessage: Message = {
          role: "assistant",
          content: demoResponses[demoKey],
          timestamp: new Date(),
        };

        setMessages((prev) => [...prev, demoMessage]);
      } else {
        toast.info("Demo mode response generated");
      }
    } finally {
      setIsThinking(false);
    }
  };

  const quickActions = [
    {
      label: "Vadodara Status",
      query: "What's the status of Vadodara flood zone?",
    },
    {
      label: "Critical Incidents",
      query: "Show me critical incidents (priority > 70)",
    },
    {
      label: "Available Teams",
      query: "How many rescue teams are available?",
    },
    {
      label: "Fire Prediction",
      query: "Predict fire spread for 12 hours with current wind",
    },
    {
      label: "My Incidents",
      query: "Show my active incidents",
    },
  ];

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <div className="max-w-4xl mx-auto p-4">
        <h1 className="text-2xl font-bold mb-6">
          AegisAI Command Center
        </h1>

        <div
          className={`mb-4 p-3 rounded-lg ${
            usingDemo
              ? "bg-red-500/20 text-red-300"
              : "bg-green-500/20 text-green-300"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="font-medium">
              {usingDemo ? "Offline Demo Mode" : "Online with Ollama"}
            </span>

            <span className="text-sm text-gray-300">
              {usingDemo ? "Local LLM unavailable" : "Connected"}
            </span>
          </div>
        </div>

        <div
          className={`h-[500px] overflow-y-auto mb-6 space-y-3 p-3 bg-gray-800/50 rounded-lg`}
        >
          {messages.map((msg, idx) => {
            const isUser = msg.role === "user";

            return (
              <div
                key={`${msg.timestamp.getTime()}-${idx}`}
                className={`flex items-start ${
                  isUser ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-xs p-3 rounded-lg ${
                    isUser
                      ? "bg-blue-600/20 text-blue-300"
                      : "bg-gray-700/20 text-gray-300"
                  }`}
                >
                  <div className="text-sm">{msg.content}</div>

                  {msg.functionCall && (
                    <div className="mt-1 text-xs text-blue-300">
                      <strong>Function:</strong>{" "}
                      {msg.functionCall.name}

                      <br />

                      <code className="text-xs">
                        {msg.functionCall.arguments}
                      </code>
                    </div>
                  )}
                </div>

                <div
                  className={`text-xs ${
                    isUser ? "text-blue-300" : "text-gray-400"
                  } ml-2 mt-1`}
                >
                  {msg.timestamp.toLocaleTimeString()}
                </div>
              </div>
            );
          })}

          {isThinking && (
            <div className="flex items-start justify-start">
              <div className="max-w-xs p-3 bg-gray-700/50 rounded-lg">
                <p className="text-sm text-gray-300">
                  Commander is thinking...
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="p-3 bg-gray-800/50 rounded-lg border-t">
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              placeholder="Type your command..."
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();

                  const value = inputRef.current?.value.trim();

                  if (value) {
                    sendQuery(value);

                    if (inputRef.current) {
                      inputRef.current.value = "";
                    }
                  }
                }
              }}
              className="flex-1 bg-gray-700 rounded-lg py-2 px-3 text-white outline-none focus:ring-2 focus:ring-blue-500"
            />

            <button
              onClick={() => {
                const value = inputRef.current?.value.trim();

                if (value) {
                  sendQuery(value);

                  if (inputRef.current) {
                    inputRef.current.value = "";
                  }
                }
              }}
              disabled={isThinking}
              className="bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-500 disabled:opacity-50"
            >
              Send
            </button>
          </div>

          <div className="mt-3 text-sm text-gray-300">
            <strong>Quick actions:</strong>

            <div className="flex flex-wrap gap-2 mt-2">
              {quickActions.map((action) => (
                <button
                  key={action.label}
                  onClick={() => sendQuery(action.query)}
                  disabled={isThinking}
                  className="text-xs text-blue-300 underline cursor-pointer disabled:opacity-50"
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};