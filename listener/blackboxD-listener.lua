#!/usr/bin/env lua
-- blackboxd-listener.lua — Native Hyprland IPC event listener via socket2

local socket = require("socket")
local socket_unix = require("socket.unix")

-- Configuration
local CONFIG = {
    api_host = os.getenv("BLACKBOXD_HOST") or "127.0.0.1",
    api_port = tonumber(os.getenv("BLACKBOXD_PORT")) or 9099,
    reconnect_delay = 2,
    debug = os.getenv("BLACKBOXD_DEBUG") == "1",
}

-- Events that affect workspace state
local WORKSPACE_EVENTS = {
    workspace = true,
    focusedmon = true,
    createworkspace = true,
    destroyworkspace = true,
    moveworkspace = true,
    renameworkspace = true,
    activespecial = true,
    activelayout = true,
}

local function log(level, msg)
    if level == "DEBUG" and not CONFIG.debug then return end
    io.stderr:write(string.format("[%s] %s: %s\n", os.date("%H:%M:%S"), level, msg))
end

local function get_hyprland_socket_path()
    local signature = os.getenv("HYPRLAND_INSTANCE_SIGNATURE")
    if not signature then
        log("ERROR", "HYPRLAND_INSTANCE_SIGNATURE not set — is Hyprland running?")
        os.exit(1)
    end
    
    local xdg_runtime = os.getenv("XDG_RUNTIME_DIR") or "/run/user/" .. (os.getenv("UID") or "1000")
    return string.format("%s/hypr/%s/.socket2.sock", xdg_runtime, signature)
end

local function notify_api(event_type, data)
    local tcp = socket.tcp()
    tcp:settimeout(2)
    
    local ok, err = tcp:connect(CONFIG.api_host, CONFIG.api_port)
    if not ok then
        log("WARN", "API unreachable: " .. (err or "unknown error"))
        tcp:close()
        return false
    end
    
    -- POST to /api/refresh endpoint
    local body = string.format('{"event":"%s","data":"%s"}', event_type, data or "")
    local request = string.format(
        "POST /api/refresh HTTP/1.1\r\n" ..
        "Host: %s:%d\r\n" ..
        "Content-Type: application/json\r\n" ..
        "Content-Length: %d\r\n" ..
        "Connection: close\r\n\r\n%s",
        CONFIG.api_host, CONFIG.api_port, #body, body
    )
    
    tcp:send(request)
    tcp:close()
    
    log("DEBUG", string.format("Notified API: %s", event_type))
    return true
end

local function parse_event(line)
    -- Hyprland socket2 format: eventname>>data
    local event, data = line:match("^([^>]+)>>(.*)$")
    return event, data
end

local function connect_to_hyprland()
    local socket_path = get_hyprland_socket_path()
    log("INFO", "Connecting to: " .. socket_path)
    
    local conn = socket_unix()
    local ok, err = conn:connect(socket_path)
    
    if not ok then
        log("ERROR", "Failed to connect: " .. (err or "unknown"))
        return nil
    end
    
    conn:settimeout(0.1)  -- Non-blocking with short timeout for clean shutdown
    log("INFO", "Connected to Hyprland socket2")
    return conn
end

local function main_loop()
    local conn = connect_to_hyprland()
    if not conn then
        os.exit(1)
    end
    
    local buffer = ""
    local running = true
    
    -- Handle SIGTERM/SIGINT gracefully
    local function cleanup()
        running = false
        if conn then conn:close() end
        log("INFO", "Listener stopped")
    end
    
    log("INFO", "Listening for workspace events...")
    
    while running do
        local chunk, err = conn:receive(4096)
        
        if chunk then
            buffer = buffer .. chunk
            
            -- Process complete lines
            while true do
                local newline_pos = buffer:find("\n")
                if not newline_pos then break end
                
                local line = buffer:sub(1, newline_pos - 1)
                buffer = buffer:sub(newline_pos + 1)
                
                if #line > 0 then
                    local event, data = parse_event(line)
                    
                    if event then
                        log("DEBUG", string.format("Event: %s -> %s", event, data or ""))
                        
                        if WORKSPACE_EVENTS[event] then
                            notify_api(event, data)
                        end
                    end
                end
            end
        elseif err == "timeout" then
            -- Normal timeout, continue loop
            socket.sleep(0.05)
        elseif err == "closed" then
            log("WARN", "Connection closed by Hyprland")
            break
        else
            log("ERROR", "Socket error: " .. (err or "unknown"))
            break
        end
    end
    
    cleanup()
end

-- Reconnection wrapper
local function run_with_reconnect()
    while true do
        local ok, err = pcall(main_loop)
        if not ok then
            log("ERROR", "Listener crashed: " .. tostring(err))
        end
        
        log("INFO", string.format("Reconnecting in %d seconds...", CONFIG.reconnect_delay))
        socket.sleep(CONFIG.reconnect_delay)
    end
end

-- Entry point
log("INFO", "BlackboxD Hyprland Listener starting...")
run_with_reconnect()
