#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${SWARM_DRONES_ROOT:-$HOME/Programs/SWARM_DRONES}"
ACTION="${1:-status}"

PID_DIRECTORY="/tmp/v1_swarm_camera_servers"
LOG_DIRECTORY="/tmp/v1_swarm_camera_logs"

START_TIMEOUT_S="${CAMERA_START_TIMEOUT_S:-240}"
CHECK_INTERVAL_S="${CAMERA_CHECK_INTERVAL_S:-3}"

mkdir -p \
    "$PID_DIRECTORY" \
    "$LOG_DIRECTORY"

port_for_drone() {
    local drone_number="$1"
    echo "$((5010 + drone_number))"
}

port_is_listening() {
    local port="$1"

    ss -ltnH 2>/dev/null |
        awk '{print $4}' |
        grep -Eq ":${port}$"
}

http_is_ready() {
    local port="$1"

    local status

    status="$(
        curl \
            -s \
            --max-time 3 \
            -o /dev/null \
            -w '%{http_code}' \
            "http://127.0.0.1:${port}/" \
            2>/dev/null ||
        true
    )"

    [[ "$status" == "200" ]]
}

stop_server() {
    local drone_number="$1"
    local pid_file="$PID_DIRECTORY/drone_${drone_number}.pid"

    if [[ ! -f "$pid_file" ]]; then
        echo "drone_${drone_number}: no managed PID"
        return
    fi

    local pid
    pid="$(cat "$pid_file")"

    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM -- "-$pid" 2>/dev/null ||
            kill -TERM "$pid" 2>/dev/null ||
            true

        sleep 2

        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL -- "-$pid" 2>/dev/null ||
                kill -KILL "$pid" 2>/dev/null ||
                true
        fi
    fi

    rm -f "$pid_file"

    echo "drone_${drone_number}: stopped"
}

start_server() {
    local drone_number="$1"
    local drone_id="drone_${drone_number}"
    local port
    port="$(port_for_drone "$drone_number")"

    local pid_file="$PID_DIRECTORY/${drone_id}.pid"
    local log_file="$LOG_DIRECTORY/${drone_id}.log"

    if port_is_listening "$port" && http_is_ready "$port"; then
        echo "${drone_id}: already READY | port=${port}"
        return 0
    fi

    if [[ -f "$pid_file" ]]; then
        local old_pid
        old_pid="$(cat "$pid_file")"

        if kill -0 "$old_pid" 2>/dev/null; then
            stop_server "$drone_number"
        else
            rm -f "$pid_file"
        fi
    fi

    rm -f "$log_file"

    echo
    echo "========================================"
    echo "STARTING ${drone_id}"
    echo "========================================"
    echo "Expected port: ${port}"
    echo "Timeout: ${START_TIMEOUT_S} seconds"

    nohup setsid env \
        OMP_NUM_THREADS=1 \
        MKL_NUM_THREADS=1 \
        OPENBLAS_NUM_THREADS=1 \
        NUMEXPR_NUM_THREADS=1 \
        "$PROJECT_ROOT/simulation/scripts/start_yolo_for_swarm_drone_port.sh" \
        "$drone_number" \
        > "$log_file" 2>&1 < /dev/null &

    local pid="$!"
    echo "$pid" > "$pid_file"

    echo "${drone_id}: process started | pid=${pid}"

    local elapsed=0

    while (( elapsed < START_TIMEOUT_S )); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo
            echo "ERROR: ${drone_id} process exited."

            tail -n 120 "$log_file" || true
            return 1
        fi

        local subscriber_ready=0
        local port_ready=0
        local http_ready=0

        if grep -q \
            "Subscribed to ROS image topic" \
            "$log_file" \
            2>/dev/null
        then
            subscriber_ready=1
        fi

        if port_is_listening "$port"; then
            port_ready=1
        fi

        if http_is_ready "$port"; then
            http_ready=1
        fi

        printf \
            "\r%s | elapsed=%ss | model/node=%s | port=%s | http=%s" \
            "$drone_id" \
            "$elapsed" \
            "$subscriber_ready" \
            "$port_ready" \
            "$http_ready"

        if (( subscriber_ready == 1 &&
              port_ready == 1 &&
              http_ready == 1 ))
        then
            echo
            echo "${drone_id}: READY | pid=${pid} | port=${port}"
            return 0
        fi

        sleep "$CHECK_INTERVAL_S"
        elapsed=$((elapsed + CHECK_INTERVAL_S))
    done

    echo
    echo "ERROR: ${drone_id} did not become ready."

    echo
    echo "===== ${drone_id} LOG ====="
    tail -n 160 "$log_file" || true

    stop_server "$drone_number"

    return 1
}

show_status() {
    echo "===== CAMERA SERVER STATUS ====="

    local ready_count=0

    for drone_number in 1 2 3; do
        local drone_id="drone_${drone_number}"
        local pid_file="$PID_DIRECTORY/${drone_id}.pid"
        local port
        port="$(port_for_drone "$drone_number")"

        local process_state="STOPPED"
        local port_state="CLOSED"
        local http_state="OFFLINE"
        local pid="none"

        if [[ -f "$pid_file" ]]; then
            pid="$(cat "$pid_file")"

            if kill -0 "$pid" 2>/dev/null; then
                process_state="RUNNING"
            else
                process_state="STALE"
            fi
        fi

        if port_is_listening "$port"; then
            port_state="LISTENING"
        fi

        if http_is_ready "$port"; then
            http_state="READY"
        fi

        if [[ "$process_state" == "RUNNING" &&
              "$port_state" == "LISTENING" &&
              "$http_state" == "READY" ]]
        then
            ready_count=$((ready_count + 1))
        fi

        echo \
"${drone_id}: process=${process_state} | pid=${pid} | port=${port_state} | http=${http_state} | feed=http://127.0.0.1:${port}/video_feed"
    done

    echo
    echo "Ready camera servers: ${ready_count}/3"

    [[ "$ready_count" -eq 3 ]]
}

start_all() {
    for drone_number in 1 2 3; do
        if ! start_server "$drone_number"; then
            echo
            echo "Camera startup failed. Stopping all camera servers."

            for number in 1 2 3; do
                stop_server "$number" || true
            done

            exit 1
        fi

        echo "Waiting before loading the next model stack..."
        sleep 5
    done

    echo
    show_status
}

case "$ACTION" in
    start)
        start_all
        ;;

    stop)
        for drone_number in 1 2 3; do
            stop_server "$drone_number"
        done
        ;;

    restart)
        "$0" stop
        sleep 3
        "$0" start
        ;;

    status)
        show_status
        ;;

    logs)
        for drone_number in 1 2 3; do
            echo
            echo "===== DRONE ${drone_number} ====="

            tail -n 100 \
                "$LOG_DIRECTORY/drone_${drone_number}.log" \
                2>/dev/null ||
                echo "No log available"
        done
        ;;

    follow)
        tail -F \
            "$LOG_DIRECTORY"/drone_*.log
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|logs|follow}"
        exit 1
        ;;
esac
