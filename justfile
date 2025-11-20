default:
  just --list
run:
  dtach -A ./bot script -a -c "python ./bot.py"
watch:
  tail -f ./typescript
attach:
  dtach -a ./bot
