const hre = require('hardhat');

async function main() {
  const Verification = await hre.ethers.getContractFactory('Verification');
  const verification = await Verification.deploy();
  await verification.waitForDeployment();

  console.log('Verification deployed to:', await verification.getAddress());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
