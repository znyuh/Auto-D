# Default values
src_path="./configs/proto/task_message.proto"
out_dir="./proto/"

if [ $# -eq 2 ]; then
    src_path=$1
    out_dir=$2
elif [ $# -eq 1 ]; then

    src_path=$1
elif [ $# -gt 2 ]; then
    echo "Error: Too many arguments"
    echo "Usage: $0 [src_path] [out_dir]"
    exit 1
fi

if [ ! -f "$src_path" ]; then
    echo "Error: Source file '$src_path' does not exist"
    exit 1
fi

if [ ! -d "$out_dir" ]; then
    echo "Error: Output directory '$out_dir' does not exist"
    exit 1
fi

src_dir=$(dirname "$src_path")
src_file=$(basename "$src_path")

protoc --python_out=$out_dir --proto_path=$src_dir $src_file