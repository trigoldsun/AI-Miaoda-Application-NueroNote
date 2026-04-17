-- Lua filter for log enrichment

function add_trace_id(tag, timestamp, record)
    -- Generate or extract trace ID
    local trace_id = record["trace_id"]
    
    if trace_id == nil or trace_id == "" then
        -- Generate a simple trace ID
        local uuid = string.format("%08x", os.time()) .. "-" .. string.format("%04x", math.random(0, 0xffff))
        record["trace_id"] = uuid
    end
    
    -- Ensure timestamp is properly formatted
    if record["time"] then
        record["@timestamp"] = record["time"]
    end
    
    -- Add Kubernetes metadata if available
    if record["kubernetes"] then
        local k8s = record["kubernetes"]
        record["pod_name"] = k8s["pod_name"] or "unknown"
        record["namespace"] = k8s["namespace_name"] or "unknown"
        record["container_name"] = k8s["container_name"] or "unknown"
        record["pod_ip"] = k8s["pod_ip"] or "unknown"
        
        -- Extract labels
        if k8s["labels"] then
            record["app"] = k8s["labels"]["app"] or "unknown"
            record["component"] = k8s["labels"]["component"] or "unknown"
        end
    end
    
    -- Calculate log level severity
    local level = record["level"] or "info"
    if level == "debug" then
        record["severity"] = 0
    elseif level == "info" then
        record["severity"] = 1
    elseif level == "warn" or level == "warning" then
        record["severity"] = 2
    elseif level == "error" then
        record["severity"] = 3
    elseif level == "fatal" or level == "critical" then
        record["severity"] = 4
    else
        record["severity"] = 1
    end
    
    -- Remove nested kubernetes object to avoid duplication
    -- record["kubernetes"] = nil
    
    return 1, timestamp, record
end
