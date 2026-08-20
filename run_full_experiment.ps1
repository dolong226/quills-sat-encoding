
python .\transpile_investigation\transpile_for_quills.py .\benchmarks\queko\queko16 guadalupe -o .\benchmarks\transpiled\queko\queko16 --batch

python .\src\main.py .\benchmarks\transpiled\queko\queko16 --output results_lb_transpiled_queko_16.csv