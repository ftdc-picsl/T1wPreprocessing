#!/bin/bash

function usage {
    echo "Usage: $0 [command]"
    echo "Available commands:"
    echo "  prepare_input       Prepare input data for hd-bet"
    echo "  run_hdbet           Run hd-bet on the prepared input"
    echo "  run_postprocessing  Run postprocessing on hd-bet output"
    echo
    echo "Run any command with --help for more information."
    exit 1
}

# print usage
if [[ $# -eq 0 ]]; then
    usage
fi

# Catch attempt to get help with -h
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
fi

script="/opt/bin/run_${1}.py"
shift

if [[ -f "${script}" ]]; then
    $script "$@"
else
    echo "Error: Unknown command '${1}'"
    exit 1
fi
