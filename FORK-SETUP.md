# Fork Setup Instructions for Mofa-AI-Tech

## Current Status
✅ Created branch `tencent-cloud-optimization` with all changes committed
✅ Ready to push to Mofa-AI-Tech fork

## Next Steps

### 1. Create Fork (if not done yet)
1. Go to https://github.com/allenai/olmocr
2. Click "Fork" → Select "Mofa-AI-Tech" as owner
3. Create the fork

### 2. Add Fork Remote and Push
```bash
# Add the Mofa-AI-Tech fork as a remote
git remote add mofa https://github.com/Mofa-AI-Tech/olmocr.git

# Push our optimization branch to the fork
git push mofa tencent-cloud-optimization

# Optional: Also push main branch to keep it up to date
git checkout main
git push mofa main
```

### 3. Create Pull Request (Optional)
If you want to propose these changes back to the original repository:
```bash
# Go to https://github.com/Mofa-AI-Tech/olmocr
# Click "Compare & pull request" for the tencent-cloud-optimization branch
# Target: allenai/olmocr:main ← Mofa-AI-Tech/olmocr:tencent-cloud-optimization
```

## Files Added in This Branch
- `CLAUDE.md` - Claude Code guidance file
- `Dockerfile.tencent` - Optimized Dockerfile for Tencent Cloud
- `README-TENCENT.md` - Comprehensive deployment documentation
- `docker-build-tencent.sh` - Build script
- `FORK-SETUP.md` - This instruction file

## What's Ready
🚀 **Production Ready**: All files are committed and ready for Tencent Cloud deployment
📦 **Pre-downloaded Models**: ~15GB models cached in image
☁️ **Cloud-init Support**: Full Tencent Cloud Batch Compute compatibility

## Quick Deploy
Once the fork is set up:
```bash
cd /path/to/mofa-olmocr
git checkout tencent-cloud-optimization
./docker-build-tencent.sh
```