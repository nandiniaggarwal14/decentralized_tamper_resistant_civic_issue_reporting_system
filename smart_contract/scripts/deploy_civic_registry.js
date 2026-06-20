/**
 * Deploy script for CivicRegistry.sol
 *
 * Usage:
 *   npx hardhat run scripts/deploy_civic_registry.js --network sepolia
 *
 * After deployment, update the CONTRACT_ADDRESS in the root .env file
 * with the printed address.
 */
const hre = require('hardhat');

async function main() {
  console.log('Deploying CivicRegistry to', hre.network.name, '...');

  const CivicRegistry = await hre.ethers.getContractFactory('CivicRegistry');
  const registry = await CivicRegistry.deploy();
  await registry.waitForDeployment();

  const address = await registry.getAddress();
  console.log('CivicRegistry deployed to:', address);
  console.log('');
  console.log('Next steps:');
  console.log(`  1. Update CONTRACT_ADDRESS in .env to: ${address}`);
  console.log('  2. Copy the ABI from artifacts/contracts/CivicRegistry.sol/CivicRegistry.json');
  console.log('     to backend/app/CivicRegistry.json');
  console.log('  3. Restart the backend server');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
