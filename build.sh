# build project
make config-pisa
make

# test if cache simulator works
#./sim-cache -cache:dl1 none -cache:dl2 none -cache:il1 il1:256:32:1:l -cache:il2 none -tlb:itlb none -tlb:dtlb none -redir:prog /dev/null -redir:sim output_block_32 tests-pisa/bin.little/test-fmath
#cat output_block_32
